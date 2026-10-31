import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse


def main():
    parser = argparse.ArgumentParser(description='将真实发布文件的大小和 SHA-256 写入引擎下载清单，不构建或上传文件')
    parser.add_argument('kind', choices=['engine', 'model'])
    parser.add_argument('key', choices=['macos-arm64', 'macos-x64', 'windows-x64', 'light', 'balanced', 'advanced'])
    parser.add_argument('--file', required=True, type=Path)
    parser.add_argument('--url', help='引擎包已发布的真实 HTTPS 地址；模型沿用清单中的官方地址')
    args = parser.parse_args()
    manifest_path = Path(__file__).resolve().parents[1] / 'backend' / 'engine-downloads.json'
    manifest = json.loads(manifest_path.read_text())
    group = 'engines' if args.kind == 'engine' else 'models'
    if args.key not in manifest[group]:
        parser.error('文件类型与平台或模型档位不匹配')
    if not args.file.is_file() or args.file.stat().st_size == 0:
        parser.error('请提供真实、完整的发布文件')
    entry = manifest[group][args.key]
    if args.kind == 'engine':
        parsed = urlparse(args.url or '')
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            parser.error('引擎包必须提供已发布的真实 HTTPS 地址')
        if args.file.suffix.lower() != '.' + entry['format']:
            parser.error('引擎包文件格式必须与清单定义一致')
        entry['url'] = args.url
    else:
        if args.url:
            parser.error('模型不接受覆盖官方 URL')
        if args.file.name != Path(urlparse(entry['url']).path).name:
            parser.error('模型文件名必须与已确认的官方文件名一致')
    entry['size'] = args.file.stat().st_size
    with args.file.open('rb') as source:
        entry['sha256'] = hashlib.file_digest(source, 'sha256').hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(f'已登记 {args.key} 的真实文件信息。请在发布前完成人工验收。')


if __name__ == '__main__':
    main()
