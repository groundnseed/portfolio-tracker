#!/usr/bin/env python3
"""노션 변동이력 → 종목별 현재 비중 자동 산출 → index.html 갱신.

입력: notion_entries.json (auto-sync agent가 노션 MCP로 fetch 후 저장)
  형식: [{"date": "YYYY-MM-DD", "summary": "...", "detail": "...", "weight": 96.5}, ...]
출력: index.html의 holdings 배열 + stockReturns pct를 정확히 동기화.

핵심 원칙:
- DETERMINISTIC: 동일 입력 → 동일 출력 (agent의 hallucination 차단)
- VALIDATION: replay 후 합계가 마지막 entry의 비중(%)와 ±0.5%p 이내 일치하지 않으면 abort
- IDEMPOTENT: 여러번 실행해도 안전

사용법:
  python scripts/sync_positions.py notion_entries.json
"""
import sys, re, json
from pathlib import Path
from collections import defaultdict

# ─── 이름 ⇄ 티커 매핑 (노션 상세 내용의 표기 ↔ index.html ticker) ──
NAME_TO_TICKER = {
    # 🇰🇷 KR
    'KODEX200': 'KRX:069500', 'KODEX 200': 'KRX:069500', '코덱스200': 'KRX:069500',
    '삼성전기': 'KRX:009150',
    'OCI': 'KRX:010060', 'OCI홀딩스': 'KRX:010060',
    'SK하이닉스': 'KRX:000660', '하이닉스': 'KRX:000660', 'SK Hynix': 'KRX:000660',
    '삼성전자': 'KRX:005930', '삼전': 'KRX:005930',
    'KB금융': 'KRX:105560', 'KB': 'KRX:105560',
    '두산에너': 'KRX:034020', '두산에너빌리티': 'KRX:034020', '두빌': 'KRX:034020', '두에빌': 'KRX:034020',
    '미래에셋': 'KRX:006800', '미래에셋증권': 'KRX:006800',
    'LS Elec': 'KRX:010120', 'LS ELECTRIC': 'KRX:010120', 'LS일렉': 'KRX:010120', 'LS일렉트릭': 'KRX:010120',
    '현대건설': 'KRX:000720',
    '현대차': 'KRX:005380',
    # 🇺🇲 US
    'IWM': 'NYSEARCA:IWM', 'iShares Russell 2000': 'NYSEARCA:IWM',
    'INTC': 'NASDAQ:INTC', '인텔': 'NASDAQ:INTC', 'Intel': 'NASDAQ:INTC',
    'AVGO': 'NASDAQ:AVGO', 'Broadcom': 'NASDAQ:AVGO', '브로드컴': 'NASDAQ:AVGO',
    'LRCX': 'NASDAQ:LRCX', 'Lam Research': 'NASDAQ:LRCX', '램리서치': 'NASDAQ:LRCX', '램': 'NASDAQ:LRCX',
    'VRT': 'NYSE:VRT', 'Vertiv': 'NYSE:VRT', '버티브': 'NYSE:VRT',
    'C': 'NYSE:C', 'CITY': 'NYSE:C', 'Citigroup': 'NYSE:C', '시티': 'NYSE:C',
    'SNDK': 'NASDAQ:SNDK', 'SanDisk': 'NASDAQ:SNDK',
    'CAT': 'NYSE:CAT', 'Caterpillar': 'NYSE:CAT', '캐터': 'NYSE:CAT',
    'LITE': 'NASDAQ:LITE', 'Lumentum': 'NASDAQ:LITE', '루멘텀': 'NASDAQ:LITE',
    'GOOG': 'NASDAQ:GOOGL', 'GOOGL': 'NASDAQ:GOOGL', 'Alphabet': 'NASDAQ:GOOGL',
    'Alphabet A': 'NASDAQ:GOOGL', '알파벳': 'NASDAQ:GOOGL', '구글': 'NASDAQ:GOOGL',
}

# 티커 → 표시 정보 (US English / KR Korean) — index.html 표기 통일
TICKER_DISPLAY = {
    'KRX:069500': {'short': 'KODEX200', 'long': 'KODEX 200', 'market': 'kr'},
    'KRX:009150': {'short': '삼성전기', 'long': '삼성전기', 'market': 'kr'},
    'KRX:010060': {'short': 'OCI', 'long': 'OCI홀딩스', 'market': 'kr'},
    'KRX:000660': {'short': 'SK하이닉스', 'long': 'SK하이닉스', 'market': 'kr'},
    'KRX:005930': {'short': '삼성전자', 'long': '삼성전자', 'market': 'kr'},
    'KRX:105560': {'short': 'KB금융', 'long': 'KB금융', 'market': 'kr'},
    'KRX:034020': {'short': '두산에너', 'long': '두산에너빌리티', 'market': 'kr'},
    'KRX:006800': {'short': '미래에셋', 'long': '미래에셋증권', 'market': 'kr'},
    'KRX:010120': {'short': 'LS Elec', 'long': 'LS ELECTRIC', 'market': 'kr'},
    'KRX:000720': {'short': '현대건설', 'long': '현대건설', 'market': 'kr'},
    'KRX:005380': {'short': '현대차', 'long': '현대차', 'market': 'kr'},
    'NYSEARCA:IWM': {'short': 'IWM', 'long': 'iShares Russell 2000', 'market': 'us'},
    'NASDAQ:INTC': {'short': 'INTC', 'long': 'Intel', 'market': 'us'},
    'NASDAQ:AVGO': {'short': 'AVGO', 'long': 'Broadcom', 'market': 'us'},
    'NASDAQ:LRCX': {'short': 'LRCX', 'long': 'Lam Research', 'market': 'us'},
    'NYSE:VRT': {'short': 'VRT', 'long': 'Vertiv', 'market': 'us'},
    'NYSE:C': {'short': 'CITY', 'long': 'Citigroup', 'market': 'us'},
    'NASDAQ:SNDK': {'short': 'SNDK', 'long': 'SanDisk', 'market': 'us'},
    'NYSE:CAT': {'short': 'CAT', 'long': 'Caterpillar', 'market': 'us'},
    'NASDAQ:LITE': {'short': 'LITE', 'long': 'Lumentum', 'market': 'us'},
    'NASDAQ:GOOGL': {'short': 'GOOGL', 'long': 'Alphabet A', 'market': 'us'},
}


def parse_deltas(detail_text):
    """상세 내용 텍스트에서 (ticker, before, after) 튜플 리스트 추출.

    매칭 패턴: 라인 단위로 '(BEFORE→AFTER)' 또는 '편출 (B→0)' 같은 형태 찾고,
    그 앞에 등장하는 가장 긴 매칭 종목명을 찾음.
    """
    deltas = []
    # 줄/구분자 단위로 split
    for line in re.split(r'[\n•·,]', detail_text):
        line = line.strip()
        if not line:
            continue
        # 패턴: ( BEFORE → AFTER ) — →/->/~ 모두 허용
        m = re.search(r'\(\s*([\d.]+)\s*(?:→|->|~)\s*([\d.]+)\s*\)', line)
        if not m:
            continue
        try:
            before, after = float(m.group(1)), float(m.group(2))
        except ValueError:
            continue
        # 종목명 찾기: 괄호 앞부분에서 NAME_TO_TICKER의 가장 긴 매칭 키
        prefix = line[:m.start()]
        best_name = None
        for name in sorted(NAME_TO_TICKER, key=len, reverse=True):  # 긴 것부터
            if name in prefix:
                best_name = name
                break
        if best_name:
            deltas.append((NAME_TO_TICKER[best_name], before, after, best_name))
        else:
            print(f'⚠️  unknown stock in line: "{line}"', file=sys.stderr)
    return deltas


def replay_positions(entries):
    """노션 entries를 날짜순으로 replay해서 최종 ticker → pct 산출."""
    entries_sorted = sorted(entries, key=lambda e: e.get('date', ''))
    positions = defaultdict(float)
    for entry in entries_sorted:
        detail = entry.get('detail', '')
        if not detail:
            continue
        for ticker, before, after, name in parse_deltas(detail):
            positions[ticker] = after  # AFTER value 그대로 사용
    # 0인 항목 제거
    return {t: p for t, p in positions.items() if p > 0.001}


def update_index_html(positions, last_weight, html_path='index.html'):
    """index.html의 holdings + stockReturns 갱신.

    holdings: 새 배열로 완전 교체 (KR 먼저, US 뒤, 각각 pct desc)
    stockReturns: 기존 항목의 pct만 업데이트, basisPrice/currentPrice/returnPct 유지.
    """
    p = Path(html_path)
    src = p.read_text(encoding='utf-8')

    # 합계 validation
    total = sum(positions.values())
    if last_weight is not None:
        diff = abs(total - last_weight)
        if diff > 0.5:
            print(f'❌ 합계 불일치: replay={total:.2f}%, 노션 마지막={last_weight:.2f}% (diff={diff:.2f}%p)',
                  file=sys.stderr)
            print(f'   abort. 노션 변동이력 누락이나 파싱 실패 가능성. 수동 검증 필요.', file=sys.stderr)
            return False
        print(f'✓ 합계 검증: replay {total:.1f}% == 노션 {last_weight:.1f}% (diff {diff:.2f}%p)')

    # ── 1. holdings 배열 재구성 ──
    # KR 먼저 (pct desc), US 뒤 (pct desc)
    sorted_pos = sorted(
        positions.items(),
        key=lambda kv: (TICKER_DISPLAY.get(kv[0], {}).get('market', 'z'), -kv[1])
    )
    lines = ['    const holdings = [']
    last_market = None
    for ticker, pct in sorted_pos:
        info = TICKER_DISPLAY.get(ticker)
        if not info:
            print(f'⚠️  no display info for {ticker}', file=sys.stderr)
            continue
        if info['market'] != last_market:
            lines.append(f"      // {'🇰🇷 KR' if info['market'] == 'kr' else '🇺🇲 US (내림차순 정렬)'}")
            last_market = info['market']
        lines.append(f"      {{ name:'{info['short']}', market:'{info['market']}', pct:{pct:.1f} }},")
    # 마지막 콤마 제거
    if lines[-1].endswith(','):
        lines[-1] = lines[-1].rstrip(',')
    lines.append('    ];')
    new_holdings_str = '\n'.join(lines)

    src = re.sub(
        r'    const holdings = \[.*?\n    \];',
        new_holdings_str.replace('\\', r'\\'),
        src, count=1, flags=re.DOTALL
    )

    # ── 2. stockReturns: pct만 업데이트, 기타 필드 유지. 누락된 종목은 추가, 0이 된 종목은 제거 ──
    m = re.search(r'const stockReturns = (\[.*?\n\s*\]);', src, re.DOTALL)
    stocks = json.loads(m.group(1))

    # 기존 stocks를 ticker로 인덱싱
    existing = {s['ticker']: s for s in stocks}
    new_stocks = []
    for ticker, pct in sorted_pos:
        info = TICKER_DISPLAY.get(ticker, {})
        if ticker in existing:
            s = existing[ticker]
            s['pct'] = pct
            # name도 표준화
            s['name'] = info.get('long', s['name'])
            new_stocks.append(s)
        else:
            new_stocks.append({
                'ticker': ticker,
                'name': info.get('long', ticker),
                'market': info.get('market', 'us'),
                'pct': pct,
                'basisPrice': None,
                'currentPrice': None,
                'returnPct': 0,
            })

    new_arr = json.dumps(new_stocks, ensure_ascii=False, indent=4)
    src = re.sub(
        r'const stockReturns = \[.*?\n\s*\];',
        f'const stockReturns = {new_arr};',
        src, count=1, flags=re.DOTALL
    )

    p.write_text(src, encoding='utf-8')
    print(f'\n✓ index.html 갱신 완료 (holdings {len(positions)}종목, 합계 {total:.1f}%)')
    return True


def main():
    if len(sys.argv) < 2:
        print('Usage: python sync_positions.py <notion_entries.json>', file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], encoding='utf-8') as f:
        entries = json.load(f)

    print(f'📥 {len(entries)}개 노션 entry 로드')

    # 마지막 entry의 비중(%) — validation용
    sorted_entries = sorted(entries, key=lambda e: e.get('date', ''))
    last_weight = None
    if sorted_entries:
        last_weight = sorted_entries[-1].get('weight')

    positions = replay_positions(entries)
    if not positions:
        print('❌ replay 결과 비어있음. 파싱 실패 가능성.', file=sys.stderr)
        sys.exit(1)

    print(f'\n📊 replay 결과 — {len(positions)}종목:')
    for ticker, pct in sorted(positions.items(), key=lambda kv: -kv[1]):
        info = TICKER_DISPLAY.get(ticker, {})
        print(f"  {ticker:20} {info.get('short', '?'):15} {pct:.1f}%")

    ok = update_index_html(positions, last_weight)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
