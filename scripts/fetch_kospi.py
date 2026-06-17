#!/usr/bin/env python3
"""KOSPI 종합지수 일별 종가 fetch → index.html에 kospiByDate inline 저장."""
import urllib.request, json, re, sys
from datetime import date, datetime, timedelta

def fetch_yahoo(symbol, start_str, end_str):
    p1 = int(datetime.strptime(start_str, '%Y-%m-%d').timestamp())
    p2 = int((datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=2)).timestamp())
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}&period2={p2}&interval=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read())
    res = data['chart']['result'][0]
    ts = res['timestamp']
    closes = res['indicators']['quote'][0]['close']
    out = {}
    for i, t in enumerate(ts):
        dt = datetime.fromtimestamp(t)
        d = f'{dt.month}/{dt.day}'
        if closes[i] is not None: out[d] = round(closes[i], 2)
    return out

def main():
    today = date.today().strftime('%Y-%m-%d')
    print('Fetching KOSPI ^KS11...')
    kospi = fetch_yahoo('^KS11', '2026-03-09', today)
    print(f'  {len(kospi)} 거래일, latest: {sorted(kospi.items())[-1]}')

    with open('index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    wd = json.loads(re.search(r'const weightDates = (\[.*?\]);', html).group(1))
    # forward-fill
    last = None
    kospi_filled = {}
    for d in wd:
        if d in kospi: last = kospi[d]
        if last is not None: kospi_filled[d] = last

    # inline insert (weightDates 다음에)
    if 'const kospiByDate =' in html:
        html = re.sub(r'const kospiByDate = \{[^}]*\};', f'const kospiByDate = {json.dumps(kospi_filled)};', html)
    else:
        # NAV 다음 위치 (트렌드 차트 생성 전)에 삽입
        m = re.search(r'(const NAV = \d+;\s*\n)', html)
        if not m:
            m = re.search(r'(const weightDates = \[.*?\];\s*\n)', html, re.DOTALL)
        html = html[:m.end()] + f'    const kospiByDate = {json.dumps(kospi_filled)};\n' + html[m.end():]

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'✓ kospiByDate 저장 ({len(kospi_filled)} 일자)')

if __name__ == '__main__':
    sys.exit(main())
