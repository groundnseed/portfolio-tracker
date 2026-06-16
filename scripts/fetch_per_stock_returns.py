#!/usr/bin/env python3
"""종목별 일일 수익률 시계열을 yahoo finance에서 fetch.

로직:
1. index.html의 stockReturns 읽기 (ticker, basisPrice 필요)
2. 각 ticker에 대해 3/10부터 오늘까지 daily close fetch
3. 일별 수익률 = (close - basisPrice) / basisPrice * 100
4. perStockHistory 배열에 returnHistory: [{date, r}, ...] 필드 추가/갱신
5. weightDates도 3/10부터 시작하도록 확장 + weights에 보간(현재값 유지)

Usage:
  python scripts/fetch_per_stock_returns.py
  python scripts/fetch_per_stock_returns.py --start 2026-03-10
"""
import urllib.request, json, re, sys, argparse
from datetime import date, datetime, timedelta

KR_TICKERS = {
    'KRX:069500': '069500.KS', 'KRX:009150': '009150.KS', 'KRX:010060': '010060.KS',
    'KRX:000660': '000660.KS', 'KRX:005930': '005930.KS', 'KRX:105560': '105560.KS',
    'KRX:034020': '034020.KS', 'KRX:006800': '006800.KS', 'KRX:010120': '010120.KS',
    'KRX:000720': '000720.KS', 'KRX:005380': '005380.KS',
    'KRX:064400': '064400.KS', 'KRX:016360': '016360.KS',
}
US_TICKERS = {
    'NYSEARCA:IWM': 'IWM', 'NASDAQ:INTC': 'INTC', 'NASDAQ:AVGO': 'AVGO',
    'NASDAQ:LRCX': 'LRCX', 'NYSE:VRT': 'VRT', 'NYSE:C': 'C',
    'NASDAQ:SNDK': 'SNDK', 'NYSE:CAT': 'CAT', 'NASDAQ:LITE': 'LITE',
    'NASDAQ:GOOGL': 'GOOGL',
    'NASDAQ:DDOG': 'DDOG', 'NYSE:BE': 'BE', 'NASDAQ:ARM': 'ARM', 'NASDAQ:CSCO': 'CSCO', 'NASDAQ:MRVL': 'MRVL', 'NYSE:GS': 'GS',
}

def fetch_close_history(yahoo_symbol, start: date, end: date):
    """{date(YYYY-MM-DD): close} dict 반환"""
    p1 = int(datetime.combine(start - timedelta(days=2), datetime.min.time()).timestamp())
    p2 = int(datetime.combine(end + timedelta(days=2), datetime.min.time()).timestamp())
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}'
           f'?period1={p1}&period2={p2}&interval=1d')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    r = data['chart']['result'][0]
    ts = r['timestamp']
    closes = r['indicators']['quote'][0]['close']
    out = {}
    for i, t in enumerate(ts):
        d = datetime.fromtimestamp(t).strftime('%Y-%m-%d')
        if closes[i] is not None:
            out[d] = closes[i]
    return out


def m_d(date_str):
    """YYYY-MM-DD → M/D"""
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    return f'{dt.month}/{dt.day}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default='2026-03-10')
    ap.add_argument('--end', default=None, help='YYYY-MM-DD (default today)')
    args = ap.parse_args()

    start = datetime.strptime(args.start, '%Y-%m-%d').date()
    end = datetime.strptime(args.end, '%Y-%m-%d').date() if args.end else date.today()
    print(f'기간: {start} ~ {end}')

    with open('index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    # stockReturns 추출
    sr_m = re.search(r'const stockReturns = (\[.*?\]);', html, re.DOTALL)
    sr = json.loads(sr_m.group(1))
    print(f'stockReturns: {len(sr)} 종목')

    # 각 종목의 ticker → yahoo symbol 매핑
    ticker_map = {**KR_TICKERS, **US_TICKERS}

    # ticker별 일별 close fetch
    histories = {}  # name → [{date(YYYY-MM-DD), close}]
    sr_updates = {}  # name → updated basis/current (for stockReturns 갱신)
    for s in sr:
        ticker = s.get('ticker', '')
        name = s['name']
        basis = s.get('basisPrice')
        ysym = ticker_map.get(ticker)
        if not ysym:
            print(f'  - skip {name} ({ticker}): no ticker map')
            continue
        try:
            closes = fetch_close_history(ysym, start, end)
            sorted_dates = sorted(closes.keys())
            # basisPrice 없으면 첫 fetch close 를 basisPrice 로 자동 설정
            if not basis:
                if not sorted_dates:
                    print(f'  - skip {name}: no data')
                    continue
                # 신규편입일 추정: 6/14 직전 close (있으면), 없으면 첫 close
                target = '2026-06-12'
                basis_date = sorted_dates[0]
                for d in sorted_dates:
                    if d <= target:
                        basis_date = d
                basis = closes[basis_date]
                sr_updates[name] = {'basisPrice': round(basis, 2), 'currentPrice': round(closes[sorted_dates[-1]], 2)}
                print(f'  ⚡ {name} basis 자동: {basis:.2f} ({basis_date})')
            histories[name] = [{'date': d, 'close': closes[d], 'r': round((closes[d] - basis) / basis * 100, 2)}
                                for d in sorted_dates]
            print(f'  ✓ {name:20s} ({ysym:12s}) {len(histories[name])} 거래일')
        except Exception as e:
            print(f'  ✗ {name} ({ysym}): {e}', file=sys.stderr)
            histories[name] = []

    # perStockHistory 배열 갱신 — returnHistory 필드 추가
    psh_m = re.search(r'const perStockHistory = (\[.*?\]);', html, re.DOTALL)
    if not psh_m:
        print('ERROR: perStockHistory 못 찾음', file=sys.stderr)
        return 1
    psh = json.loads(psh_m.group(1))
    for s in psh:
        name = s['name']
        if name in histories:
            # returnHistory: [{date: 'M/D', r: %.2f}]
            s['returnHistory'] = [{'date': m_d(h['date']), 'r': h['r']} for h in histories[name]]

    new_psh_js = '[\n' + ',\n'.join('      ' + json.dumps(x, ensure_ascii=False) for x in psh) + '\n    ]'
    html = html.replace(psh_m.group(0), 'const perStockHistory = ' + new_psh_js + ';', 1)

    # stockReturns 자동 보정 (basisPrice/currentPrice None 인 종목)
    if sr_updates:
        for s in sr:
            if s['name'] in sr_updates:
                u = sr_updates[s['name']]
                if not s.get('basisPrice'): s['basisPrice'] = u['basisPrice']
                if not s.get('currentPrice'): s['currentPrice'] = u['currentPrice']
                if s.get('basisPrice'):
                    s['returnPct'] = round((s['currentPrice']-s['basisPrice'])/s['basisPrice']*100, 2)
        new_sr_js = '[\n' + ',\n'.join('    ' + json.dumps(x, ensure_ascii=False) for x in sr) + '\n    ]'
        html = html.replace(sr_m.group(0), 'const stockReturns = ' + new_sr_js + ';', 1)
        print(f'✓ stockReturns 자동 보정: {list(sr_updates.keys())}')

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'✓ perStockHistory에 returnHistory 필드 추가 ({sum(1 for s in psh if s.get("returnHistory"))} 종목)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
