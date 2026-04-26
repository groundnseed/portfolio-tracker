#!/usr/bin/env python3
"""Yahoo Finance에서 종가 fetch → index.html의 currentPrice/returnPct 업데이트.
Usage: python scripts/update_prices.py --market kr|us
"""
import urllib.request, json, re, argparse, sys

KR_TICKERS = {
    'KRX:069500': '069500.KS',  # KODEX 200
    'KRX:009150': '009150.KS',  # 삼성전기
    'KRX:010060': '010060.KS',  # OCI홀딩스
    'KRX:000660': '000660.KS',  # SK하이닉스
    'KRX:005930': '005930.KS',  # 삼성전자
    'KRX:105560': '105560.KS',  # KB금융
    'KRX:034020': '034020.KS',  # 두산에너빌리티
    'KRX:006800': '006800.KS',  # 미래에셋증권
    'KRX:010120': '010120.KS',  # LS ELECTRIC
    'KRX:000720': '000720.KS',  # 현대건설
    'KRX:005380': '005380.KS',  # 현대차
}

US_TICKERS = {
    'NYSEARCA:IWM': 'IWM',
    'NASDAQ:INTC': 'INTC',
    'NASDAQ:AVGO': 'AVGO',
    'NASDAQ:LRCX': 'LRCX',
    'NYSE:VRT': 'VRT',
    'NYSE:C': 'C',
    'NASDAQ:SNDK': 'SNDK',
    'NYSE:CAT': 'CAT',
    'NASDAQ:LITE': 'LITE',
    'NASDAQ:GOOGL': 'GOOGL',
}


def fetch_price(ticker):
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
        return data['chart']['result'][0]['meta']['regularMarketPrice']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['kr', 'us'], required=True)
    args = parser.parse_args()

    tickers = KR_TICKERS if args.market == 'kr' else US_TICKERS
    flag = '🇰🇷' if args.market == 'kr' else '🇺🇲'

    print(f'{flag} Fetching {len(tickers)} {args.market.upper()} prices...')
    prices = {}
    for full, yh in tickers.items():
        try:
            prices[full] = fetch_price(yh)
            print(f'  {yh:12} {prices[full]}')
        except Exception as e:
            print(f'  FAIL {yh}: {e}', file=sys.stderr)

    if not prices:
        print('No prices fetched, exiting (likely market holiday)')
        sys.exit(0)

    with open('index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    updates = 0
    print('\n--- patches ---')
    for full, new_price in prices.items():
        pattern = re.compile(
            r'("ticker":\s*"' + re.escape(full) + r'"[^{}]*?"basisPrice":\s*)([0-9.]+|null)'
            r'([^{}]*?"currentPrice":\s*)([0-9.]+|null)'
            r'([^{}]*?"returnPct":\s*)(-?[0-9.]+)',
            re.DOTALL
        )
        m = pattern.search(html)
        if not m:
            print(f'  NO MATCH {full}')
            continue
        basis_str = m.group(2)
        old_cur = m.group(4)
        if basis_str == 'null':
            new_html = pattern.sub(
                lambda x: x.group(1) + x.group(2) + x.group(3) + str(new_price) + x.group(5) + x.group(6),
                html, count=1
            )
            print(f'  {full}: {old_cur} -> {new_price} (basisPrice null)')
        else:
            basis = float(basis_str)
            return_pct = round((new_price - basis) / basis * 100, 2)
            new_html = pattern.sub(
                lambda x: x.group(1) + x.group(2) + x.group(3) + str(new_price) + x.group(5) + str(return_pct),
                html, count=1
            )
            print(f'  {full}: {old_cur} -> {new_price}  ({return_pct:+.2f}%)')
        if new_html != html:
            html = new_html
            updates += 1

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'\n{flag} {args.market.upper()} 종목 {updates}/{len(prices)} 업데이트 완료')


if __name__ == '__main__':
    main()
