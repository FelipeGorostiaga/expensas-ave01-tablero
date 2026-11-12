#!/usr/bin/env python3
"""Parse Octopus-generated 'liquidación de expensas' PDFs into structured JSON.

Usage: python parse_expensas.py <folder-with-pdfs> <output.json>

Each PDF is a monthly settlement with three parts:
  1. the expense ledger grouped by rubro (category)
  2. the financial / patrimonial statements
  3. the per-unit account statement ("estado de cuenta y prorrateo")
The parser validates every month: item sums must match the printed rubro
totals and the grand total, and unit rows must match the printed totals row.
"""
import glob, json, os, re, sys
from collections import defaultdict
import pdfplumber

AMT = re.compile(r'^-?\$[\d.]+,\d{2}$')
MONTHS = {'ENERO':1,'FEBRERO':2,'MARZO':3,'ABRIL':4,'MAYO':5,'JUNIO':6,'JULIO':7,
          'AGOSTO':8,'SEPTIEMBRE':9,'OCTUBRE':10,'NOVIEMBRE':11,'DICIEMBRE':12}

def money(s):
    return float(s.replace('$','').replace('.','').replace(',','.'))

def pct(s):
    return float(s.replace(',','.'))

def page_words(page):
    """Words of a page with the rotated left-margin watermark removed."""
    fp = page.filter(lambda o: o['object_type'] != 'char' or o['x0'] >= 30)
    return fp.extract_words(x_tolerance=1.5, keep_blank_chars=False), fp.extract_text() or ''

def cluster_lines(words, tol=3.0):
    words = sorted(words, key=lambda w: (w['top'], w['x0']))
    lines = []
    for w in words:
        if lines and abs(lines[-1]['top'] - w['top']) <= tol:
            lines[-1]['words'].append(w)
        else:
            lines.append({'top': w['top'], 'words': [w]})
    for ln in lines:
        ln['words'].sort(key=lambda w: w['x0'])
        ln['amts'] = [w for w in ln['words'] if AMT.match(w['text'])]
        ln['txt_words'] = [w for w in ln['words'] if w not in ln['amts']]
        ln['text'] = ' '.join(w['text'] for w in ln['txt_words']).strip()
        ln['x0'] = ln['txt_words'][0]['x0'] if ln['txt_words'] else None
    return lines

RUBRO_HDR = re.compile(r'^(\d{1,2}) ([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ,/\.]+)$')
RUBRO_TOT = re.compile(r'^Total (.+?) % ([\d.,]+)$')
ITEM_FULL = re.compile(r'^(?P<prov>.+?) - (?P<cuit>\d{2}-\d{8}-\d)?\s?- (?P<date>\d{2}/\d{2}/\d{4}) - ?(?P<desc>.*)$')
ITEM_DATE = re.compile(r'^(?P<date>\d{2}/\d{2}/\d{4}) - (?P<desc>.*)$')
ITEM_PROV_DATE = re.compile(r'^(?P<prov>[^$]+?) - (?P<date>\d{2}/\d{2}/\d{4}) - ?(?P<desc>.*)$')
ITEM_NODATE = re.compile(r'^(?P<prov>.+?) - (?P<cuit>\d{2}-\d{8}-\d)?\s?- (?P<desc>.*)$')
SKIP = re.compile(r'^(\d+ de \d+|Procesado por OCTOPUS.*|Ante cualquier irregularidad.*|facebook\.com.*|SIN MOVIMIENTOS)$')

def col_of(x1):
    if x1 > 520: return 'total'
    if x1 > 440: return 'abl'
    return 'expensas'

def looks_like_start(text):
    return bool(ITEM_FULL.match(text) or ITEM_DATE.match(text) or ITEM_PROV_DATE.match(text))

def build_item(block, rubro):
    text = re.sub(r'\s+', ' ', ' '.join(block['lines'])).strip()
    text = re.sub(r'(\d{2})- (\d{8}-\d)', r'\1-\2', text)            # CUIT split across lines
    text = re.sub(r'(N[ºo°]\s*\d+)- (\d+)', r'\1-\2', text)            # invoice number split across lines
    rec = {'rubro': rubro, 'raw': text, 'provider': None, 'cuit': None, 'date': None,
           'description': text, 'expensas': 0.0, 'abl': 0.0, 'total': None, 'amount_cols': []}
    m = ITEM_FULL.match(text) or ITEM_DATE.match(text) or ITEM_PROV_DATE.match(text) or ITEM_NODATE.match(text)
    if m:
        g = m.groupdict()
        rec['provider'] = (g.get('prov') or '').strip() or None
        rec['cuit'] = g.get('cuit')
        rec['date'] = g.get('date')
        rec['description'] = g['desc'].strip()
    for col, val in block['amts']:
        rec[col] = val
        rec['amount_cols'].append(col)
    if rec['total'] is None:
        rec['total'] = round(rec['expensas'] + rec['abl'], 2)
    inv = re.search(r'FC\s*N[ºo°]\s*([\d-]+)', text)
    rec['invoice'] = inv.group(1).strip('-') if inv else None
    low = text.lower()
    rec['is_provision'] = bool(re.search(r'previsi[oó]n', low)) and 'reintegro' not in low
    rec['is_reversal'] = bool(re.search(r'reint[er]*gro|reintregro', low)) or bool(re.search(r'reint', low))
    rec['is_provision'] = rec['is_provision'] and not rec['is_reversal']
    rec['provider_inferred'] = False
    if rec['provider'] is None and rec['is_reversal'] and 'cuota' in low:
        rec['provider'] = 'AGIP INM/ABL'; rec['provider_inferred'] = True
    if rec['provider'] is None:
        if 'gastos bancarios' in low: rec['group'] = 'Gastos bancarios'
        elif 'iva sobre honorarios' in low or 'iva s/ honorarios' in low: rec['group'] = 'IVA s/ honorarios administración'
        elif 'seguro' in low: rec['group'] = 'Seguro (sin proveedor)'
        else: rec['group'] = 'Compras varias (sin proveedor)'
    else:
        rec['group'] = rec['provider']
    cuota = re.search(r'cuota\s+(\d+)\s*/\s*(\d+)', low)
    rec['installment'] = f'{cuota.group(1)}/{cuota.group(2)}' if cuota else None
    return rec

def segment_page(lines, state):
    """Walk one ledger page. state holds rubro / started / results. Returns list of blocks."""
    blocks = []      # each: {'lines': [], 'tops': [], 'amts': [], 'rubro': ..., 'kind': 'item'}
    pending_amts = []
    cur = None
    last_top = None
    for ln in lines:
        t = ln['text']
        if state['done']:
            break
        if t.startswith('TOTAL DE GASTOS EN $'):
            vals = [money(x) for x in re.findall(r'-?\$[\d.]+,\d{2}', ' '.join(w['text'] for w in ln['words']))]
            state['grand'] = {'expensas': vals[0], 'abl': vals[1], 'total': vals[2]} if len(vals) >= 3 else {'expensas': vals[0], 'abl': 0.0, 'total': vals[-1]}
            state['done'] = True
            break
        mh = RUBRO_HDR.match(t)
        if mh and ln['x0'] is not None and ln['x0'] < 50 and not ln['amts']:
            cur = None; last_top = None
            state['rubro'] = mh.group(2).strip()
            state['rubro_no'] = int(mh.group(1))
            blocks.append({'kind': 'rubro', 'rubro': state['rubro']})
            continue
        if state.get('rubro_no', 0) < 2:
            # salary table (rubro 1) has its own format and has been empty; capture its total if any
            mt = re.search(r'TOTAL RUBRO\s*%\s*([\d.,]+)\s*\$\s*([\d.,]+)', ' '.join(w['text'] for w in ln['words']))
            if mt:
                state['sueldos_total'] = money(mt.group(2))
            continue
        mt = RUBRO_TOT.match(t)
        if mt:
            cur = None; last_top = None
            blocks.append({'kind': 'total', 'rubro': mt.group(1).strip(), 'pct': pct(mt.group(2)),
                           'total': money(ln['amts'][-1]['text']) if ln['amts'] else 0.0})
            continue
        if SKIP.match(t) and not ln['amts']:
            continue
        if ln['txt_words'] and ln['x0'] is not None and ln['x0'] < 48 and not ln['amts']:
            continue  # stray header line
        if ln['txt_words']:
            if cur is None or (last_top is not None and ln['top'] - last_top > 13):
                cur = {'kind': 'item', 'lines': [], 'tops': [], 'amts': [], 'rubro': state['rubro']}
                blocks.append(cur)
            cur['lines'].append(t); cur['tops'].append(ln['top'])
            last_top = ln['top']
        for a in ln['amts']:
            pending_amts.append((ln['top'], col_of(a['x1']), money(a['text'])))
    # assign amounts to the vertically closest item block
    items = [b for b in blocks if b['kind'] == 'item']
    for top, col, val in pending_amts:
        best, bestd = None, 1e9
        for b in items:
            lo, hi = min(b['tops']) - 7, max(b['tops']) + 7
            d = 0 if lo <= top <= hi else min(abs(top - lo), abs(top - hi))
            if d < bestd:
                best, bestd = b, d
        if best is not None:
            best['amts'].append((col, val))
    return blocks

def parse_ledger(pages):
    state = {'rubro': None, 'rubro_no': 0, 'done': False, 'grand': None, 'sueldos_total': 0.0}
    items, rubro_totals = [], []
    prev_item = None   # last item block from the previous page (for cross-page continuation)
    for lines in pages:
        if state['done']: break
        blocks = segment_page(lines, state)
        first_item_seen = False
        for b in blocks:
            if b['kind'] == 'rubro':
                prev_item = None
                continue
            if b['kind'] == 'total':
                rubro_totals.append({'rubro': b['rubro'], 'pct': b['pct'], 'total': b['total']})
                prev_item = None
                continue
            text = ' '.join(b['lines'])
            if not first_item_seen and prev_item is not None and not looks_like_start(text):
                # continuation of an item that was cut by the page break
                prev_item['lines'] += b['lines']; prev_item['amts'] += b['amts']
                first_item_seen = True
                continue
            first_item_seen = True
            if not b['amts'] and prev_item is not None and not looks_like_start(text):
                prev_item['lines'] += b['lines']
                continue
            items.append(b)
            prev_item = b
    recs = [build_item(b, b['rubro']) for b in items if b['amts'] or looks_like_start(' '.join(b['lines']))]
    if state['sueldos_total']:
        recs.insert(0, build_item({'lines': ['Sueldos y cargas sociales (total del rubro)'], 'amts': [('total', state['sueldos_total'])]}, 'REMUNERACIONES AL PERSONAL Y CARGAS SOCIALES'))
    return recs, rubro_totals, state['grand']

TOK = re.compile(r'-?\$[\d.]+,\d{2}|\d+\.\d+|\S+')
MONEY = re.compile(r'^-?\$[\d.]+,\d{2}$')
PCT = re.compile(r'^\d+\.\d+$')
PISO = re.compile(r'^(PB|SS|EP|\d{1,2})$')

def unit_columns(header_text):
    """Which optional columns this month's prorrateo table carries."""
    return {'avaluo': 'AVALUO' in header_text, 'gast': 'GAST.' in header_text, 'cargos': 'Cargos Part.' in header_text}

def split_numeric_tail(nums, cols):
    """nums: numeric tokens after UF/PISO/OWNER. Returns dict or None."""
    if len(nums) < 10 or not all(MONEY.match(n) or PCT.match(n) for n in nums):
        return None
    out = {'saldo_ant': money(nums[0]), 'pago': money(nums[1]), 'deuda': money(nums[2]), 'intereses': money(nums[3])}
    i = 4
    pairs = []
    while i + 1 < len(nums) and PCT.match(nums[i]) and MONEY.match(nums[i+1]):
        pairs.append((pct(nums[i]), money(nums[i+1]))); i += 2
    trailing = [money(n) for n in nums[i:]]
    if len(pairs) < 3 or len(trailing) < 2:
        return None
    out['coef'], out['expensas'] = pairs[0]
    out['coef_extra'], out['extraordinarios'] = pairs[1]
    if len(pairs) >= 4:
        out['coef_avaluo'], out['abl_avaluo'] = pairs[2]
        out['coef_abl'], out['abl'] = pairs[3]
    else:
        out['coef_avaluo'], out['abl_avaluo'] = 0.0, 0.0
        out['coef_abl'], out['abl'] = pairs[2]
    out['total'] = trailing.pop(); out['redondeo'] = trailing.pop()
    out['gastos_part'] = 0.0; out['cargos_part'] = 0.0
    # remaining trailing columns, in header order: GAST. PART. then Cargos Part.
    names = ([ 'gastos_part'] if cols['gast'] else []) + (['cargos_part'] if cols['cargos'] else [])
    if len(names) != len(trailing):
        # header detection disagreed with the row; fall back to position
        names = ['gastos_part', 'cargos_part'][-len(trailing):] if trailing else []
    for n, v in zip(names, trailing):
        out[n] = v
    return out

def parse_units(text):
    units, totals = [], None
    seen_uf = {}
    header = text[:text.find('\n', text.find('UF ')) + 200] if 'UF ' in text else text[:600]
    cols = unit_columns(header)
    for raw in text.split('\n'):
        line = raw.strip()
        if not line: continue
        toks = TOK.findall(line)
        first_num = next((k for k, t in enumerate(toks) if MONEY.match(t)), None)
        if first_num is None: continue
        lead, nums = toks[:first_num], toks[first_num:]
        vals = split_numeric_tail(nums, cols)
        if vals is None: continue
        if not lead:
            totals = vals
            continue
        piso_idx = None
        for i in range(len(lead) - 1, 0, -1):
            if PISO.match(lead[i]) and i < len(lead) - 1:
                piso_idx = i; break
        glued = re.match(r'^([A-Z]+\d+|\d+)(PB|SS|EP)$', lead[0]) if piso_idx is None else None
        if glued:
            lead = [glued.group(1), glued.group(2)] + lead[1:]
            piso_idx = 1
        if piso_idx is None:
            piso_idx = len(lead) - 1
        uf_raw = ' '.join(lead[:piso_idx])
        flags = re.search(r'(\*+)$', uf_raw)
        rec = {'uf': uf_raw.rstrip('*').strip(), 'flag': flags.group(1) if flags else '', 'piso': lead[piso_idx],
               'owner': ' '.join(lead[piso_idx+1:])}
        rec.update(vals)
        k = rec['uf']
        seen_uf[k] = seen_uf.get(k, 0) + 1
        if seen_uf[k] > 1:
            rec['uf'] = f"{k} ({seen_uf[k]})"
        units.append(rec)
    return units, totals

def parse_statements(pages):
    """Return ordered (label, amount) rows for the financial and patrimonial statements."""
    allines = []
    for lines in pages:
        for k, ln in enumerate(lines):
            allines.append((ln, k == 0))
    fin, pat = [], []
    section = None
    cur = None; last_top = None
    for ln, page_start in allines:
        if page_start: last_top = None
        t = ln['text']
        if t == 'ESTADO FINANCIERO': section = 'fin'; cur = None; continue
        if t == 'ESTADO PATRIMONIAL': section = 'pat'; cur = None; continue
        if t.startswith('MOVIMIENTOS BANCARIOS SIN IDENTIFICAR'): section = None; cur = None; continue
        if section is None: continue
        if SKIP.match(t) or t.startswith('(Conf.') or t == 'CONCEPTO': continue
        target = fin if section == 'fin' else pat
        if ln['txt_words']:
            if cur is None or (cur['amount'] is not None and (last_top is None or ln['top'] - last_top > 13)) or (ln['x0'] is not None and ln['x0'] > 100 and not ln['amts']) or (cur['amount'] is None and ln['amts'] and last_top is not None and ln['top'] - last_top > 13):
                cur = {'label': '', 'amount': None}
                target.append(cur)
            cur['label'] = (cur['label'] + ' ' + t).strip()
            last_top = ln['top']
        if ln['amts']:
            if cur is None:
                cur = {'label': '', 'amount': None}; target.append(cur)
            cur['amount'] = money(ln['amts'][-1]['text'])
    fin = [r for r in fin if r['amount'] is not None or r['label']]
    pat = [r for r in pat if r['amount'] is not None or r['label']]
    return fin, pat

def row_value(rows, label):
    for r in rows:
        if r['label'] == label:
            return r['amount']
    return None

def parse_pdf(path):
    ledger_pages, unit_text, full_text = [], '', ''
    with pdfplumber.open(path) as pdf:
        for p in pdf.pages:
            words, text = page_words(p)
            full_text += text + '\n'
            if 'ESTADO DE CUENTA Y PRORRATEO' in text:
                unit_text += text + '\n'
            else:
                ledger_pages.append(cluster_lines(words))
    per = re.search(r'LIQUIDACIÓN DE MES (\w+) (\d{4})', full_text)
    month_name, year = per.group(1), int(per.group(2))
    period = f'{year}-{MONTHS[month_name]:02d}'
    vto = re.search(r'1° VTO: (\d{2}/\d{2}/\d{4})', full_text)
    items, rubro_totals, grand = parse_ledger(ledger_pages)
    units, unit_totals = parse_units(unit_text)
    fin_rows, pat_rows = parse_statements(ledger_pages)
    fin = {
        'saldo_inicial': row_value(fin_rows, 'SALDO INICIAL'),
        'ingreso_en_termino': row_value(fin_rows, 'INGRESO POR PAGO DE EXPENSAS EN TERMINO'),
        'ingreso_adeudadas': row_value(fin_rows, 'INGRESO POR PAGO DE EXPENSAS ADEUDADAS'),
        'ingreso_intereses': row_value(fin_rows, 'INGRESO POR PAGO DE INTERESES'),
        'devoluciones': row_value(fin_rows, 'DEVOLUCIONES'),
        'ingresos_sin_identificar': row_value(fin_rows, 'INGRESOS SIN IDENTIFICAR'),
        'egresos_gastos_mes': row_value(fin_rows, 'EGRESOS POR GASTOS DEL MES'),
        'saldo_cierre': row_value(fin_rows, 'SALDO AL CIERRE'),
        'otros_egresos': [r for r in fin_rows if r['label'].startswith('OTROS EGRESOS')],
        'rows': fin_rows,
    }
    pat = {
        'disponibilidades': row_value(pat_rows, 'SALDO DE DISPONIBILIDADES AL CIERRE'),
        'a_cobrar': row_value(pat_rows, 'EXPENSAS Y OTROS CONCEPTOS A COBRAR'),
        'devengados_pendientes': row_value(pat_rows, 'GASTOS DEVENGADOS PENDIENTES DE PAGO'),
        'patrimonio_neto': row_value(pat_rows, 'PATRIMONIO NETO AL CIERRE'),
        'rows': pat_rows,
    }
    notes = re.search(r'^NOTAS\n(.*?)^FORMAS DE PAGO', full_text, re.S | re.M)
    juicios = re.search(r'DATOS DE JUICIOS.*?\n(.*?)\nREFERENCIA DE PROVEEDORES', full_text, re.S)
    sin_ident = re.search(r'MOVIMIENTOS BANCARIOS SIN IDENTIFICAR\n(.*?)\nMOVIMIENTOS BANCARIOS IDENTIFICADOS', full_text, re.S)
    providers = []
    for line in full_text[full_text.find('REFERENCIA DE PROVEEDORES'):].split('\n'):
        mm = re.match(r'^(.+?) - CUIT: ?([\d-]*)(?: - (.*))?$', line.strip())
        if not mm: continue
        parts = mm.group(1).split(' - ')
        providers.append((parts[0].strip(), mm.group(2), ' - '.join(parts[1:]).strip(), (mm.group(3) or '').strip()))
    admin = re.search(r'NOMBRE:(.+?) DIRECCI', full_text)
    return {
        'period': period, 'month_name': month_name, 'year': year,
        'due_date': vto.group(1) if vto else None,
        'grand_total': grand, 'rubro_totals': rubro_totals, 'items': items,
        'units': units, 'unit_totals': unit_totals, 'financial': fin, 'patrimonial': pat,
        'notes': notes.group(1).strip() if notes else '', 'juicios': juicios.group(1).strip() if juicios else '',
        'bank_unidentified': sin_ident.group(1).strip() if sin_ident else '',
        'provider_registry': [{'name': n, 'cuit': c, 'legal_name': l, 'address': a} for n, c, l, a in providers],
        'administration': admin.group(1).strip() if admin else None,
    }

def validate(doc):
    problems = []
    by_rubro = defaultdict(float)
    for it in doc['items']:
        by_rubro[it['rubro']] += it['total']
        if abs(it['expensas'] + it['abl'] - it['total']) > 0.011:
            problems.append(f"item split mismatch: {it['raw'][:70]} exp={it['expensas']} abl={it['abl']} tot={it['total']}")
        if len(it['amount_cols']) != len(set(it['amount_cols'])):
            problems.append(f"item got several amounts in one column (segmentation): {it['raw'][:80]}")
    for rt in doc['rubro_totals']:
        s = by_rubro.get(rt['rubro'], 0.0)
        if abs(s - rt['total']) > 0.011:
            problems.append(f"rubro {rt['rubro']}: items sum {s:,.2f} != printed {rt['total']:,.2f}")
    if doc['grand_total']:
        s = sum(it['total'] for it in doc['items'])
        if abs(s - doc['grand_total']['total']) > 0.011:
            problems.append(f"grand total: items {s:,.2f} != printed {doc['grand_total']['total']:,.2f}")
    else:
        problems.append('grand total line not found')
    ut = doc['unit_totals']
    if ut:
        for k in ('saldo_ant','pago','deuda','intereses','expensas','extraordinarios','abl_avaluo','abl','gastos_part','cargos_part','total'):
            s = sum(u[k] for u in doc['units'])
            if abs(s - ut[k]) > 1.0:
                problems.append(f"units {k}: rows sum {s:,.2f} != printed {ut[k]:,.2f}")
    else:
        problems.append('no unit totals row found')
    if doc['grand_total'] and ut and abs(doc['grand_total']['expensas'] - ut['expensas']) > 1.0:
        problems.append('expensas: ledger total != prorrateo total')
    f = doc['financial']
    if f['saldo_inicial'] is None or f['saldo_cierre'] is None:
        problems.append('financial statement incomplete')
    return problems

def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else '.'
    out = sys.argv[2] if len(sys.argv) > 2 else 'data.json'
    docs = []
    for f in sorted(glob.glob(os.path.join(folder, '*.pdf'))):
        d = parse_pdf(f)
        d['validation'] = validate(d)
        docs.append(d)
    docs.sort(key=lambda d: d['period'])
    for d in docs:
        status = 'OK' if not d['validation'] else f"{len(d['validation'])} issue(s)"
        gt = d['grand_total']['total'] if d['grand_total'] else 0
        print(f"{d['period']} {d['month_name']:<11} items={len(d['items']):3d} units={len(d['units']):3d} total={gt:>15,.2f}  {status}")
        for p in d['validation']:
            print('   -', p)
    bank_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bank_statements.json')
    bank = []
    if os.path.exists(bank_file):
        with open(bank_file, encoding='utf-8') as fh:
            bank = json.load(fh)
    payload = {'source_count': len(glob.glob(os.path.join(folder, '*.pdf'))), 'months': docs, 'bank_statements': bank}
    # newline='\n': en Windows evita CRLF, así data.enc sale idéntico byte a byte
    with open(out, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    js_out = os.path.splitext(out)[0] + '.js'
    with open(js_out, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('window.EXPENSAS = ' + json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + ';\n')
    print('wrote', out, 'and', js_out)

if __name__ == '__main__':
    main()
