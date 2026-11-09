"""Response minimization shared by the HR skill suite."""
import re
from urllib.parse import parse_qsl, urlsplit

MASK = '[REDACTED]'
SENSITIVE = ('salary', 'compensation', 'payroll', 'bank', 'idcard', 'idnumber', 'identitynumber', 'nationalid', 'ssn',
             'passport', 'phone', 'mobile', 'email', 'address', 'birthday', 'birthdate', 'token',
             'secret', 'password', 'apikey', '薪资', '薪酬', '工资', '身份证', '证件', '银行卡',
             '手机', '电话', '邮箱', '住址', '联系方式', '通讯地址', '联系地址', '出生日期')


def mask_data(value, secrets=()):
    if isinstance(value, dict):
        result = {}
        for key, val in value.items():
            normalized = re.sub(r'[^\w\u4e00-\u9fff]', '', key).lower().replace('_', '')
            safe_key = mask_data(key, secrets)
            result[safe_key] = MASK if any(s in normalized for s in SENSITIVE) else mask_data(val, secrets)
        return result
    if isinstance(value, list):
        return [mask_data(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, MASK)
        value = re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', MASK, value)
        value = re.sub(r'(?<!\d)1[3-9]\d{9}(?!\d)', MASK, value)
        value = re.sub(r'(?<!\d)\d{15,19}[\dXx]?(?!\d)', MASK, value)
        value = re.sub(r'((?:薪资|薪酬|工资|salary|compensation)\s*[:：=为]?\s*)[¥￥$]?\d[\d,.]*(?:[-~至]\d[\d,.]*)?(?:元|万|[kK])?',
                       lambda m: m.group(1) + MASK, value, flags=re.IGNORECASE)
    return value


def safe_link(url, hosts):
    """Allow only configured HTTPS navigation hosts, with no credentials in links."""
    if not isinstance(url, str) or any(ord(c) < 33 for c in url) or '\\' in url:
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password
                or parsed.port not in (443, None)):
            return None
        if any(any(part in k.lower() for part in ('token', 'secret', 'password', 'key', 'code'))
               for k, _ in parse_qsl(parsed.query)):
            return None
        if parsed.fragment:
            return None
        return url
    except ValueError:
        return None
