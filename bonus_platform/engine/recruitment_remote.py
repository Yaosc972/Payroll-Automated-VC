"""Authenticated read-only transport to an authorized Ego runtime."""
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit

MAX_RESPONSE = 32 * 1024 * 1024
PATH = '/v1/recruitment/overseas-snapshot'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class RemoteClient:
    def __init__(self):
        self.url = os.getenv('SIGMA_RECRUITMENT_OVERSEAS_CONNECTOR_URL', '').rstrip('/')
        self.token = os.getenv('SIGMA_RECRUITMENT_OVERSEAS_CONNECTOR_TOKEN', '')
        try:
            parsed = urlsplit(self.url)
            valid = (parsed.scheme == 'https' and parsed.hostname and parsed.path in {'', PATH}
                     and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)
        except ValueError:
            valid = False
        if not valid or not self.token:
            raise ValueError('海外 Ego 取数端尚未接通，请联系管理员配置 HTTPS 连接器和凭据')
        if not parsed.path:
            self.url += PATH
        self.opener = urllib.request.build_opener(NoRedirect)

    def fetch(self, month, job_numbers=(), offer_codes=(), progress=None):
        from .recruitment_overseas import _month, _numbers, validate_snapshot
        from .recruitment_cancellation import checkpoint
        _month(month)
        checkpoint()
        payload = {'month': month, 'jobNumbers': _numbers(job_numbers), 'offerCodes': _numbers(offer_codes)}
        if any(len(payload[k]) > 5000 for k in ('jobNumbers', 'offerCodes')):
            raise ValueError('本次海外查询范围过大')
        if progress:
            progress('正在通过已授权的海外 Ego 取数端读取资料')
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
        try:
            with self.opener.open(request, timeout=900) as response:
                content = response.read(MAX_RESPONSE + 1)
                if len(content) > MAX_RESPONSE:
                    raise ValueError('海外取数响应过大，本次未保存新快照')
                result = json.loads(content)
        except urllib.error.HTTPError as exc:
            messages = {401: '海外取数端凭据失效，请联系管理员', 409: '海外取数端正在处理其他任务，请稍后重试',
                        424: '请在海外取数端登录 HRMS 和 OEHR 后重试，已有资料保留'}
            raise ValueError(messages.get(exc.code, '海外取数端未完整返回，本次未保存新快照')) from None
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            raise ValueError('海外取数端连接或响应异常，本次未保存新快照') from None
        checkpoint()
        return validate_snapshot(result, month)


def configured_client():
    from ..auth import production_runtime
    from .recruitment_overseas import BrowserClient
    if production_runtime() or os.getenv('SIGMA_RECRUITMENT_OVERSEAS_CONNECTOR_URL'):
        return RemoteClient()
    return BrowserClient()
