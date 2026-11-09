"""Package only maintained skill resources, never local secrets or outputs."""
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RELEASE_FILES = (
    'SKILL.md', 'README.md', 'LICENSE.txt', 'agents/openai.yaml',
    'references/recruitment.md', 'references/lifecycle.md', 'references/people-operations.md',
    'references/data-rules.md', 'references/connectors.md', 'references/acceptance.md',
    'assets/configs/connector.example.json', 'assets/templates/employees.csv', 'assets/templates/payroll.csv',
    'assets/templates/performance.csv', 'assets/templates/recruitment.md', 'assets/templates/lifecycle.md',
    'assets/templates/people-operations.md', 'assets/templates/index.md',
    'scripts/hr_local.py', 'scripts/hr_connect.py', 'scripts/package_skill.py',
    'examples/local/employees.csv', 'examples/local/payroll.csv', 'examples/local/payroll-rules.json',
    'examples/local/performance.csv', 'tests/test_hr.py',
    'CONNECTORS.md', 'suite.json', 'assets/catalog/scenarios.json', 'assets/configs/query-connector.example.json',
    'references/hr-shared-rules.md', 'references/query-contract.md',
    'scripts/hr_security.py', 'scripts/hr_query.py', 'examples/queries/demo.json', 'tests/test_query.py',
    'docs/PUBLISHING.md',
)
SKILL_NAMES = ('hr-data-query', 'hr-employee-profile', 'hr-attendance-leave', 'hr-organization',
               'hr-approvals', 'hr-knowledge', 'hr-service-entry', 'hr-requisition', 'hr-position',
               'hr-talent-search', 'hr-applicant-tracking', 'hr-recruiting-todos', 'hr-recruitment-insights')
RELEASE_FILES += tuple(f'skills/{name}/{resource}' for name in SKILL_NAMES for resource in ('SKILL.md', 'agents/openai.yaml'))
RELEASE_SUFFIXES = {'.md', '.txt', '.json', '.yaml', '.py', '.csv'}


def source_path(root, name):
    """Git keeps LICENSE; the SkillHub archive uses the supported .txt suffix."""
    path = root / name
    if name == 'LICENSE.txt' and not path.exists():
        return root / 'LICENSE'
    return path


def release_payload(root):
    """Check the complete distributable before creating an archive."""
    payload = {}
    for name in RELEASE_FILES:
        p = source_path(root, name)
        if (not p.is_file() or p.is_symlink() or not p.resolve().is_relative_to(root)
                or any(part.startswith('.') or part == '..' for part in Path(name).parts)):
            raise ValueError(f'发布资源缺失或路径不安全: {name}')
        if Path(name).suffix.lower() not in RELEASE_SUFFIXES:
            raise ValueError(f'发布文件类型不在项目白名单内: {name}')
        data = p.read_bytes()
        if p.name == 'SKILL.md' and data.startswith(b'\xef\xbb\xbf'):
            raise ValueError(f'SKILL.md 必须为无 BOM UTF-8: {name}')
        text = data.decode('utf-8')
        if name.endswith('.md'):
            text = re.sub(r'(\]\()((?:\.\./)*LICENSE)(\))', r'\1\2.txt\3', text)
            text = text.replace('├── LICENSE                   ', '├── LICENSE.txt               ')
            data = text.encode('utf-8')
        payload[name] = data
    suite = json.loads(payload['suite.json'])
    version = suite.get('version', '')
    if suite.get('name') != 'hr-specialist' or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('suite.json 必须包含正确的技能名和三段式版本')
    if (suite.get('business_skill_count') != len(SKILL_NAMES)
            or [s.get('name') for s in suite.get('skills', [])] != list(SKILL_NAMES)):
        raise ValueError('suite.json 与发布技能清单不一致')
    if json.loads(payload['assets/catalog/scenarios.json']).get('version') != version:
        raise ValueError('场景目录版本与套件版本不一致')
    for name, raw in payload.items():
        text = raw.decode('utf-8')
        if name.endswith('SKILL.md'):
            match = re.search(r'^  version: "([^"]+)"\r?$', text, re.MULTILINE)
            if not match or match.group(1) != version:
                raise ValueError(f'技能版本与套件版本不一致: {name}')
        if name.endswith('.md'):
            for link in re.findall(r'\]\(([^)]+)\)', text):
                link = link.strip().strip('<>')
                if urlsplit(link).scheme or link.startswith('#'):
                    continue
                dest = ((root / name).parent / unquote(link.split('#')[0])).resolve()
                if not dest.is_relative_to(root) or dest.relative_to(root).as_posix() not in payload:
                    raise ValueError(f'文档引用未包含在发布包中: {name} -> {link}')
    for name in ('assets/configs/connector.example.json', 'assets/configs/query-connector.example.json'):
        config = json.loads(payload[name])
        if config.get('enabled') is not False:
            raise ValueError(f'分发配置必须默认关闭: {name}')
        forbidden = {'api_key', 'client_secret', 'app_secret', 'access_token', 'refresh_token', 'password', 'secret'}
        if set(config) & forbidden:
            raise ValueError(f'分发配置不能包含明文认证字段: {name}')
    return version, payload


def package(root=ROOT):
    root = Path(root).resolve()
    version, payload = release_payload(root)
    dest = root / 'dist' / 'skillhub'
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f'hr-specialist-{version}.zip'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (dest / (target.name + '.sha256')).write_text(digest + '  ' + target.name + '\n', encoding='utf-8')
    manifest = {
        'name': 'hr-specialist', 'version': version, 'archive': target.name, 'sha256': digest,
        'business_skill_count': len(SKILL_NAMES),
        'files': [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                  for name, data in sorted(payload.items())],
    }
    (dest / f'hr-specialist-{version}.manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return target, digest


if __name__ == '__main__':
    path, digest = package()
    print(str(path))
    print(digest)
