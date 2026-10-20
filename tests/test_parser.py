"""Tests for scripts/update_official.py. Run: python tests/test_parser.py"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'scripts'))
import update_official as U  # noqa: E402

from bs4 import BeautifulSoup  # noqa: E402

T = pathlib.Path(__file__).resolve().parent
today = dt.date(2026, 10, 19)
D = dt.date
bad = 0


def check(ok, what):
    global bad
    bad += not ok
    print(('OK ' if ok else 'BAD'), what)


# ------------------------------------------------------------ dates inside text
cases = {
    '2 September 2026 (Wednesday)': [D(2026, 9, 2)],
    '14 October to 31 October 2026': [D(2026, 10, 14), D(2026, 10, 31)],
    '15 October 2026, 10:30 AM to 16 October 2026, 10:29 AM': [D(2026, 10, 15), D(2026, 10, 16)],
    '6–7, 13–14, and 20–21 February 2027 (Saturday and Sunday each weekend)': [D(2027, 2, d) for d in (6, 7, 13, 14, 20, 21)],
    '16-10-2026': [D(2026, 10, 16)],
    '2026-10-16': [D(2026, 10, 16)],
    'To be announced': [],
    '12th October 2026': [D(2026, 10, 12)],
    '12 th October 2026': [D(2026, 10, 12)],
    'Sept 2, 2026': [D(2026, 9, 2)],
    'Results will be declared soon': [],
    '6th February 2027 7th February 2027': [D(2027, 2, 6), D(2027, 2, 7)],
}
for s, exp in cases.items():
    got = U.parse_dates(s)
    check(got == exp, f'{s!r} -> {[g.isoformat() for g in got]}')

check(U.norm('open till 12 th October  2026') == 'open till 12th October 2026', 'ordinals are rejoined')
check(U.compact_when('15th October 2026, 10:30AM to 16th October 2026, 10:29AM') == '15 Oct 10:30 AM to 16 Oct 10:29 AM',
      'special window note is compact')
check(U.is_day_names('Saturday Sunday') and U.is_day_names('Thursday to Friday') and not U.is_day_names('Admit Card download'),
      'day-name cells are recognised')

# ------------------------------------------------------------ cells spanning rows and columns
grid_html = '''<table>
<tr><td rowspan="3">A</td><td>b1</td><td>c1</td></tr>
<tr><td>b2</td><td>c2</td></tr>
<tr><td colspan="2">bc3</td></tr>
<tr><td>a4</td><td rowspan="2">b4</td><td>c4</td></tr>
<tr><td>a5</td><td>c5</td></tr>
</table>'''
grid = [texts for _, _, texts in U.table_rows(BeautifulSoup(grid_html, 'html.parser'))]
check(grid == [['A', 'b1', 'c1'], ['A', 'b2', 'c2'], ['A', 'bc3', 'bc3'], ['a4', 'b4', 'c4'], ['a5', 'b4', 'c5']],
      f'rowspan and colspan grid: {grid}')

# ------------------------------------------------------------ important dates pages
expected = {'reg_open': ('2026-09-02', None), 'reg_close': ('2026-10-05', None), 'reg_late': ('2026-10-12', None),
            'reg_special': ('2026-10-15', '2026-10-16'), 'rectify': ('2026-10-14', '2026-10-31'),
            'correction': (None, None), 'city': ('2027-01-04', None), 'admit': (None, None),
            'exam': ('2027-02-06', '2027-02-21'), 'result': ('2027-03-19', None)}
for f in ('fixture_dates_a.html', 'fixture_dates_b.html', 'fixture_dates_real.html'):
    rows = U.parse_schedule((T / f).read_text(), today=today)
    print('\n' + f)
    for r in rows:
        print('    ', r)
    probs = U.validate([{'x': 1}], rows)
    check(not probs, f'{f} passes validation {probs or ""}')
    got = {r['k']: (r['start'], r['end']) for r in rows}
    check(got == expected, f'{f} has exactly the expected rows' + ('' if got == expected else f': {got}'))
    exam = next((r for r in rows if r['k'] == 'exam'), {})
    check(exam.get('note', '').startswith('6–7, 13–14 and 20–21 Feb 2027'), f'{f} exam note: {exam.get("note")!r}')

real = {r['k']: r for r in U.parse_schedule((T / 'fixture_dates_real.html').read_text(), today=today)}
check(real['reg_special']['note'] == '15 Oct 10:30 AM to 16 Oct 10:29 AM, with late fee',
      f"special window note: {real['reg_special']['note']!r}")
check(real['rectify']['note'] == 'For applications with scrutiny defects', 'rectification note')

window_html = (T / 'fixture_dates_real.html').read_text().replace(
    '<td><span>TBA</span></td><td><span>TBA</span></td></tr>\n<tr><td><span>City',
    '<td><span>2<sup>nd</sup> November 2026 to 5<sup>th</sup> November 2026</span></td><td><span>Monday to Thursday</span></td></tr>\n<tr><td><span>City', 1)
win = {r['k']: r for r in U.parse_schedule(window_html, today=today)}
check((win['correction']['start'], win['correction']['end']) == ('2026-11-02', '2026-11-05'),
      f"a correction window keeps both ends: {win['correction']['start']} to {win['correction']['end']}")

# a broken read must be refused, never saved
odd = [dict(r) for r in real.values()] + [{'k': 'x_saturday_sunday', 'label': 'Saturday Sunday',
                                           'start': '2027-02-13', 'end': '2027-02-21', 'note': ''}]
check(any('odd name' in p for p in U.validate([{'x': 1}], odd)), 'a day-name row is refused')
wrong_exam = [dict(r) for r in real.values()]
for r in wrong_exam:
    if r['k'] == 'exam':
        r['start'], r['end'] = '2026-10-16', None
check(any('examination start' in p for p in U.validate([{'x': 1}], wrong_exam)), 'an impossible exam date is refused')

# ------------------------------------------------------------ notifications pages
for f in ('fixture_news.html', 'fixture_news_b.html', 'fixture_news_c.html', 'fixture_news_real.html'):
    n = U.parse_news((T / f).read_text(), today=today)
    print('\n' + f)
    for x in n:
        print('    ', x)
    check(len(n) == 2 and n[0]['date'] == '2026-10-16' and n[1]['date'] == '2026-10-14', f'{f} newest two notifications')

n = U.parse_news((T / 'fixture_news_rowspan.html').read_text(), today=D(2027, 1, 6))
print('\nfixture_news_rowspan.html')
for x in n:
    print('    ', x)
check(len(n) == 2 and [x['date'] for x in n] == ['2027-01-05', '2027-01-05']
      and n[0]['title'].startswith('Admit cards') and n[0]['url'] == 'https://goaps.iitm.ac.in/login'
      and n[1]['title'].startswith('Mock tests') and n[1]['url'] == U.NEWS_URL,
      'two notices sharing one date cell are both read, in page order')

print('\nFAILURES:', bad)
sys.exit(1 if bad else 0)
