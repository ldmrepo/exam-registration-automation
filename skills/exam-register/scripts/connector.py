"""Windows connector for an external TWK editor. Python 3.11+, stdlib only."""
import argparse
import ctypes
from ctypes import wintypes
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import warnings

VERSION = '0.1.0'


class ConnectorError(Exception):
    pass


def base_url(value):
    p = urllib.parse.urlsplit(value)
    try:
        p.port
    except ValueError:
        raise ConnectorError('잘못된 포트입니다.') from None
    if (p.scheme not in ('http', 'https') or not p.hostname or p.username
            or p.password or p.query or p.fragment or '\\' in value
            or any(ord(c) < 33 for c in value)):
        raise ConnectorError('사용자 정보·쿼리·프래그먼트 없는 서비스 주소를 입력하세요.')
    if p.scheme == 'http' and p.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ConnectorError('외부 서비스는 HTTPS가 필요합니다. HTTP는 루프백만 허용합니다.')
    return value.rstrip('/')


def state_dir():
    if os.name != 'nt':
        raise ConnectorError('v0.1.0은 Windows 전용입니다. 평문 키 저장으로 대체하지 않습니다.')
    return Path(os.environ.get('EXAM_REGISTER_HOME') or
                str(Path(os.environ['LOCALAPPDATA']) / 'ExamRegister'))


def protect(data, decrypt=False):
    if os.name != 'nt':
        raise ConnectorError('Windows DPAPI가 필요합니다.')

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    buf = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise ConnectorError('암호화 저장소 처리에 실패했습니다. 현재 Windows 계정을 확인하세요.')
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(outgoing.data)


def save_profile(profile, directory):
    # Bind destinations and key in the same encrypted object: editing a public
    # URL file cannot redirect an existing credential to a different service.
    encrypted = protect(json.dumps(profile).encode())
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=directory, suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encrypted)
        os.replace(name, directory / 'connection.dpapi')
    finally:
        Path(name).unlink(missing_ok=True)


def load_profile(directory):
    try:
        profile = json.loads(protect((directory / 'connection.dpapi').read_bytes(), True))
        profile['web_url'] = base_url(profile['web_url'])
        profile['api_url'] = base_url(profile['api_url'])
        if not isinstance(profile['key'], str) or not profile['key'].startswith('twk_'):
            raise ValueError()
        return profile
    except (OSError, ValueError, KeyError, TypeError):
        raise ConnectorError('연결 설정이 없거나 손상됐습니다. configure를 실행하세요.') from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(profile, endpoint, method='GET'):
    req = urllib.request.Request(profile['api_url'] + endpoint,
                                 headers={'Authorization': 'Bearer ' + profile['key'],
                                          'Accept': 'application/json'}, method=method)
    # Never forward a bearer token on an HTTP redirect.
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=15) as response:
            if response.status != 200 and response.status != 201:
                raise ConnectorError('예상하지 못한 HTTP 상태입니다.')
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            code = json.loads(exc.read(8192)).get('message')
        except (ValueError, AttributeError):
            code = None
        finally:
            exc.close()
        known = {'MISSING_TOKEN', 'INVALID_TOKEN', 'INVALID_HANDOFF_CODE',
                 'API_KEY_CANNOT_MANAGE_KEYS', 'PERMISSION_DENIED', 'API_KEY_NOT_FOUND'}
        safe_code = code if isinstance(code, str) and code in known else 'HTTP_ERROR'
        raise ConnectorError(f'HTTP {exc.code}: {safe_code}. 주소·키·권한을 확인하세요.') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ConnectorError('서비스에 연결하지 못했습니다. 주소와 서버 상태를 확인하세요.') from None
    except (ValueError, UnicodeError):
        raise ConnectorError('JSON 응답이 아닙니다. API 기본 주소를 확인하세요.') from None
    if not isinstance(payload, dict) or 'data' not in payload or payload.get('error'):
        raise ConnectorError('성공 응답 형식이 맞지 않습니다. {data, error, traceId}가 필요합니다.')
    return payload['data']


def handoff_url(profile, redirect='/documents'):
    # Only local document routes; do not accept arbitrary redirect input.
    if not re.fullmatch(r'/documents(?:/[A-Za-z0-9_-]+(?:/edit)?)?', redirect):
        raise ConnectorError('redirect는 /documents 또는 /documents/<ID>/edit 형식이어야 합니다.')
    data = request(profile, '/auth/handoff', 'POST')
    if not isinstance(data, dict) or not isinstance(data.get('code'), str) or not data['code']:
        raise ConnectorError('로그인 인계 코드가 응답에 없습니다.')
    return profile['web_url'] + '/auth/handoff?' + urllib.parse.urlencode(
        {'code': data['code'], 'redirect': redirect})


def install(destination):
    source = Path(__file__).resolve().parents[1]
    target = destination.resolve() / 'exam-register'
    if target == source:
        return target
    if target.is_relative_to(source) or source.is_relative_to(target):
        raise ConnectorError('설치 대상과 원본 폴더가 중첩됩니다.')
    destination.mkdir(parents=True, exist_ok=True)
    # Stage the complete copy before touching an existing installation.
    stage = Path(tempfile.mkdtemp(prefix='.exam-register-', dir=destination.parent))
    staged_skill = stage / 'exam-register'
    shutil.copytree(source, staged_skill, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    backup = None
    if target.exists():
        # Keep backups outside skills discovery, preserve the previous skill.
        backup_root = destination.parent / 'exam-register-backups'
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = backup_root / str(time.time_ns())
        target.rename(backup)
    try:
        staged_skill.rename(target)
        stage.rmdir()
    except OSError:
        if backup and not target.exists():
            backup.rename(target)
        raise
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description='외부 TWK 편집기 연결 — Windows용')
    parser.add_argument('--version', action='version', version=VERSION)
    sub = parser.add_subparsers(dest='command', required=True)
    setup = sub.add_parser('configure', help='주소와 키를 대화형으로 입력·암호화 저장')
    setup.add_argument('--web-url')
    setup.add_argument('--api-url')
    setup.add_argument('--key-stdin', action='store_true', help='자동 테스트용; 키를 명령행 인수로 받지 않음')
    sub.add_parser('status', help='키 없이 연결 주소·기록 경로 확인')
    sub.add_parser('doctor', help='문서 조회로 API 연결 검사; 문서 변경 없음')
    launch = sub.add_parser('open', help='30초 일회용 코드로 편집기 로그인')
    launch.add_argument('--redirect', default='/documents')
    launch.add_argument('--print-url', action='store_true', help='Codex 브라우저 도구용; 즉시 사용하고 기록 금지')
    inst = sub.add_parser('install', help='스킬 설치; 기존 버전은 백업')
    inst.add_argument('--destination', type=Path, default=Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'skills')
    sub.add_parser('disconnect', help='이 PC의 연결 파일 삭제; 서버 키를 폐기하지 않음')
    args = parser.parse_args(argv)
    try:
        if args.command == 'install':
            print(json.dumps({'installed': str(install(args.destination))}, ensure_ascii=False))
            return 0
        directory = state_dir()
        if args.command == 'disconnect':
            (directory / 'connection.dpapi').unlink(missing_ok=True)
            print('로컬 연결을 해제했습니다. 서버의 키 폐기는 편집기 설정에서 수행하세요.')
            return 0
        if args.command == 'configure':
            web_url = base_url(args.web_url or input('편집기 웹 주소: ').strip())
            api_url = base_url(args.api_url or input('API 기본 주소 (/api/v1 포함): ').strip())
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                try:
                    key = sys.stdin.readline().strip() if args.key_stdin else getpass.getpass('API 키 (표시되지 않음): ').strip()
                except getpass.GetPassWarning:
                    raise ConnectorError('키를 숨겨 입력할 수 없습니다. 사용자 로컬 터미널에서 configure를 실행하세요.') from None
            if not re.fullmatch(r'twk_[A-Za-z0-9_-]+', key):
                raise ConnectorError('twk_로 시작하는 API 키를 입력하세요.')
            profile = {'web_url': web_url, 'api_url': api_url, 'key': key}
            request(profile, '/documents')
            save_profile(profile, directory)
            print('연결 검사를 통과했습니다. Windows 계정으로 암호화해 저장했습니다.')
            return 0
        profile = load_profile(directory)
        if args.command == 'status':
            print(json.dumps({'version': VERSION, 'web_url': profile['web_url'],
                              'api_url': profile['api_url'], 'runs': str(directory / 'runs')}, ensure_ascii=False))
        elif args.command == 'doctor':
            request(profile, '/documents')
            print('PASS: API 인증·문서 조회 성공. 브라우저 조작과 저장은 별도 검증 대상입니다.')
        elif args.command == 'open':
            url = handoff_url(profile, args.redirect)
            if args.print_url:
                print(url)
            elif not webbrowser.open(url):
                raise ConnectorError('브라우저를 열지 못했습니다. open --print-url로 새 코드를 발급하세요.')
            else:
                print('브라우저에 로그인 인계를 요청했습니다. 문서 화면에서 성공 여부를 확인하세요.')
        return 0
    except (ConnectorError, OSError) as exc:
        # Do not echo raw server replies, URLs containing codes, or OS exceptions.
        print(str(exc) if isinstance(exc, ConnectorError) else '로컬 파일 처리에 실패했습니다.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
