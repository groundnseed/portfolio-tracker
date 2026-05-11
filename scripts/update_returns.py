#!/usr/bin/env python3
"""returnEvents에 매일 종가 기반 누적 수익률 entry 자동 추가.

로직:
1. index.html 파싱 → stockReturns(현재 보유) + returnEvents(시계열) 추출
2. returnEvents의 마지막 날짜 → 어제까지 영업일 리스트 생성
3. 각 누락된 영업일에 대해:
   - Yahoo Finance에서 그날 종가 fetch (KR+US)
   - 비중 가중평균 수익률 계산 (현재 보유 weights × 그날 close vs basisPrice)
   - returnEvents 배열에 append
4. index.html 저장

Usage:
  python scripts/update_returns.py                 # 어제까지 누락분 모두 채움
  python scripts/update_returns.py --date 2026-05-08  # 특정 일자만 추가
"""
import urllib.request, json, re, argparse, sys
from datetime import date, datetime, timedelta

# update_prices.py와 동일한 매핑 + 9개 휴장일
KR_TICKERS = {
    'KRX:069500': '069500.KS', 'KRX:009150': '009150.KS', 'KRX:010060': '010060.KS',
    'KRX:000660': '000660.KS', 'KRX:005930': '005930.KS', 'KRX:105560': '105560.KS',
    'KRX:034020': '034020.KS', 'KRX:006800': '006800.KS', 'KRX:010120': '010120.KS',
    'KRX:000720': '000720.KS', 'KRX:005380': '005380.KS',
}
US_TICKERS = {
    'NYSEARCA:IWM': 'IWM', 'NASDAQ:INTC': 'INTC', 'NASDAQ:AVGO': 'AVGO',
    'NASDAQ:LRCX': 'LRCX', 'NYSE:VRT': 'VRT', 'NYSE:C': 'C',
    'NASDAQ:SNDK': 'SNDK', 'NYSE:CAT': 'CAT', 'NASDAQ:LITE': 'LITE',
    'NASDAQ:GOOGL': 'GOOGL',
}
KR_HOLIDAYS = {date(2026,5,5), date(2026,5,24), date(2026,5,25), date(2026,6,3),
               date(2026,6,6), date(2026,8,15), date(2026,8,17)}
US_HOLIDAYS = {date(2026,5,25), date(2026,6,19), date(2026,7,3)}


def fetch_close_history(yahoo_symbol, start: date, end: date):
    """Yahoo Finance에서 특정 기간 일별 종가 fetch. {date: close} dict 반환."""
    period1 = int(datetime.combine(start - timedelta(days=2), datetime.min.time()).timestamp())
    period2 = int(datetime.combine(end + timedelta(days=2), datetime.min.time()).timestamp())
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}'
           f'?period1={period1}&period2={period2}&interval=1d')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read())
    result = data['chart']['result'][0]
    timestamps = result.get('timestamp', [])
    closes = result['indicators']['quote'][0].get('close', [])
    out = {}
    for ts, c in zip(timestamps, closes):
        if c is None: continue
        d = datetime.utcfromtimestamp(ts).date()
        out[d] = c
    return out


def parse_stock_returns(html):
    m = re.search(r'const stockReturns = (\[.*?\n\s*\]);', html, re.DOTALL)
    return json.loads(m.group(1))


def parse_return_events(html):
    m = re.search(r'const returnEvents = (\[.*?\n\s*\]);', html, re.DOTALL)
    return json.loads(m.group(1))


def compute_weighted_return(stocks, ticker_to_close):
    """시장별·전체 비중 가중 평균 수익률 (%)"""
    def avg(market_filter):
        num = den = 0.0
        for s in stocks:
            if not s.get('basisPrice') or s['pct'] <= 0: continue
            if not market_filter(s): continue
            cur = ticker_to_close.get(s['ticker'])
            if cur is None: continue
            ret = (cur - s['basisPrice']) / s['basisPrice'] * 100
            num += s['pct'] * ret
            den += s['pct']
        return round(num / den, 2) if den > 0 else 0.0
    total = avg(lambda s: True)
    kr = avg(lambda s: s['market'] == 'kr')
    us = avg(lambda s: s['market'] == 'us')
    return total, kr, us


def business_days(start: date, end_exclusive: date, holidays):
    d = start
    while d < end_exclusive:
        if d.weekday() < 5 and d not in holidays:
            yield d
        d += timedelta(days=1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', help='YYYY-MM-DD 특정일만 추가')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    with open('index.html', encoding='utf-8') as f:
        html = f.read()

    stocks = parse_stock_returns(html)
    events = parse_return_events(html)
    existing_dates = {e['date'] for e in events}

    last_date_str = events[-1]['date']
    lm, ld = map(int, last_date_str.split('/'))
    last_date = date(2026, lm, ld)

    if args.date:
        target_dates = [datetime.strptime(args.date, '%Y-%m-%d').date()]
    else:
        today = date.today()
        # today INCLUSIVE — when run before US close, fallback to most recent close works
        target_dates = list(business_days(last_date + timedelta(days=1), today + timedelta(days=1), KR_HOLIDAYS | US_HOLIDAYS))

    if not target_dates:
        print(f'✓ 이미 최신 (마지막 entry: {last_date_str})')
        return

    print(f'대상 일자: {[d.isoformat() for d in target_dates]}')

    # 한번에 전 기간 종가 fetch (API 호출 최소화)
    fetch_start, fetch_end = min(target_dates), max(target_dates)
    print(f'\nFetching Yahoo Finance closes for {fetch_start} ~ {fetch_end}...')
    ticker_history = {}
    for full, yh in {**KR_TICKERS, **US_TICKERS}.items():
        try:
            ticker_history[full] = fetch_close_history(yh, fetch_start, fetch_end)
            print(f'  ✓ {yh:12} ({len(ticker_history[full])} bars)')
        except Exception as e:
            print(f'  ✗ {yh}: {e}', file=sys.stderr)
            ticker_history[full] = {}

    new_entries = []
    for tgt in target_dates:
        m_d = f'{tgt.month}/{tgt.day}'
        if m_d in existing_dates:
            print(f'  → {m_d} skip (이미 존재)')
            continue
        # KR: 같은 날 close가 없으면 가장 가까운 이전 영업일 사용 (휴장 fallback)
        ticker_close = {}
        for full, history in ticker_history.items():
            cur = history.get(tgt)
            if cur is None:
                # fallback: 직전 영업일 종가
                for back in range(1, 5):
                    cur = history.get(tgt - timedelta(days=back))
                    if cur is not None: break
            if cur is not None:
                ticker_close[full] = cur
        if not ticker_close:
            print(f'  ⚠️  {m_d}: 종가 fetch 실패, skip')
            continue
        total, kr, us = compute_weighted_return(stocks, ticker_close)
        entry = {'date': m_d, 'totalReturn': total, 'krReturn': kr, 'usReturn': us}
        new_entries.append(entry)
        print(f'  + {m_d}: total {total:+.2f}% (kr {kr:+.2f}%, us {us:+.2f}%)')

    if not new_entries:
        print('\n변경 없음')
        return

    # returnEvents 배열에 append
    events.extend(new_entries)
    new_arr_str = json.dumps(events, ensure_ascii=False, indent=4)
    # 들여쓰기 맞춤
    new_arr_str = '\n'.join('    ' + ln if ln else ln for ln in new_arr_str.split('\n'))
    new_arr_str = new_arr_str.strip()  # outer indent handled by replacement
    new_html = re.sub(
        r'const returnEvents = \[.*?\n\s*\];',
        f'const returnEvents = {new_arr_str};',
        html, count=1, flags=re.DOTALL
    )
    if args.dry_run:
        print(f'\n[DRY RUN] {len(new_entries)}개 entry 추가 예정')
    else:
        with open('index.html', 'w', encoding='utf-8') as f:
            f.write(new_html)
        print(f'\n✓ {len(new_entries)}개 entry 추가됨')


if __name__ == '__main__':
    main()
