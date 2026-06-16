#!/usr/bin/env python3
"""USDKRW 환율 fetch + NAV 1억 기준 종목별 수익금 (원화) 시계열 계산."""
import urllib.request, json, re, sys
from datetime import date, datetime, timedelta

NAV = 100_000_000  # 1억원

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
        if closes[i] is not None:
            out[d] = closes[i]
    return out


def main():
    print('Fetching USDKRW...')
    today = date.today().strftime('%Y-%m-%d')
    fx = fetch_yahoo('KRW=X', '2026-03-09', today)
    print(f'  {len(fx)} 거래일')

    with open('index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    wd_m = re.search(r'const weightDates = (\[.*?\]);', html)
    weight_dates = json.loads(wd_m.group(1))

    psh_m = re.search(r'const perStockHistory = (\[.*?\]);', html, re.DOTALL)
    psh = json.loads(psh_m.group(1))

    # all dates union
    all_dates = set(weight_dates)
    for s in psh:
        for h in s.get('returnHistory', []):
            all_dates.add(h['date'])

    def k(d):
        m, dd = map(int, d.split('/'))
        return m * 100 + dd
    sorted_all = sorted(all_dates, key=k)

    # FX forward-fill
    fx_filled = {}
    last_fx = list(fx.values())[0] if fx else 1380
    for d in sorted_all:
        if d in fx:
            last_fx = fx[d]
        fx_filled[d] = round(last_fx, 2)

    # 종목별 매수일 환율 + 수익금 시계열
    for s in psh:
        market = s.get('market')
        weights = s.get('weights', [])
        first_buy_idx = next((i for i, w in enumerate(weights) if w > 0), 0)
        first_buy_date = weight_dates[first_buy_idx] if first_buy_idx < len(weight_dates) else weight_dates[0]
        buy_fx = fx_filled.get(first_buy_date, last_fx)
        s['buy_fx'] = buy_fx
        s['first_buy_date'] = first_buy_date

        principal = NAV * s.get('current_pct', 0) / 100
        rh = s.get('returnHistory', [])
        profit_history = []
        for entry in rh:
            d = entry['date']
            r = entry['r']
            if market == 'kr':
                profit = principal * r / 100
            else:
                fx_t = fx_filled.get(d, buy_fx)
                eval_krw = principal * (1 + r/100) * (fx_t / buy_fx)
                profit = eval_krw - principal
            profit_history.append({'date': d, 'p': round(profit)})
        s['profit_history'] = profit_history
        if profit_history:
            last = profit_history[-1]
            print(f"  {s['name']:20s} {market} buy_fx={buy_fx:.0f}  원금={principal/10000:.0f}만 최종수익={last['p']/10000:+.0f}만")

    total = sum(s['profit_history'][-1]['p'] for s in psh if s.get('profit_history'))
    print(f'\n총 수익: {total/10000:+.0f}만원 ({total/NAV*100:+.2f}%)')

    new_psh = '[\n' + ',\n'.join('      ' + json.dumps(x, ensure_ascii=False) for x in psh) + '\n    ]'
    html = html.replace(psh_m.group(0), 'const perStockHistory = ' + new_psh + ';', 1)

    # NAV + fxByDate inline 삽입 (중복 방지)
    if 'const NAV =' in html:
        html = re.sub(r'const NAV = \d+;', f'const NAV = {NAV};', html)
    else:
        html = html[:wd_m.end()] + f'\n    const NAV = {NAV};' + html[wd_m.end():]

    if 'const fxByDate =' in html:
        html = re.sub(r'const fxByDate = \{[^}]*\};', f'const fxByDate = {json.dumps(fx_filled)};', html)
    else:
        nav_pos = html.find(f'const NAV = {NAV};')
        eol = html.find('\n', nav_pos) + 1
        html = html[:eol] + f'    const fxByDate = {json.dumps(fx_filled)};\n' + html[eol:]

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print('✓ index.html 갱신')
    return 0


if __name__ == '__main__':
    sys.exit(main())
