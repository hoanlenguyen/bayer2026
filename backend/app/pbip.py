"""Deterministic PBIR demo renderer with real model bindings and offline schemas.

Target-runtime acceptance remains a separate, explicitly pending step.
"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from functools import lru_cache

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from .bindings import BINDINGS, DIMENSIONS, contract, expected_values, rows
from .governance import digest, spec_digest

SCHEMAS = Path(__file__).parent / 'schemas'
BASE = 'https://developer.microsoft.com/json-schemas/'
RENDERER_VERSION = 'pbir-demo-v1'
VISUAL_TYPES = {'card': 'card', 'bar': 'clusteredBarChart', 'line': 'lineChart', 'table': 'tableEx'}


def slug(name: str) -> str:
    return re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_')[:80] or 'Report'


def js(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + '\n'


def schema(kind: str) -> str:
    return BASE + kind + '/schema.json'


@lru_cache(maxsize=1)
def registry():
    resources = []
    for path in SCHEMAS.rglob('*.json'):
        doc = json.loads(path.read_text())
        resource = Resource.from_contents(doc)
        # Some upstream embedded schemas use a dotted $id but hyphenated file refs.
        resources.extend([(doc['$id'], resource), (BASE + path.relative_to(SCHEMAS).as_posix(), resource)])
    return Registry().with_resources(resources)


def validate_json_files(files: dict[str, str]) -> list[dict]:
    checks = []
    for path, text in files.items():
        if path.endswith(('.json', '.pbip', '.pbir', '.pbism')):
            value = json.loads(text)
            if '$schema' in value:
                definition = registry().get_or_retrieve(value['$schema']).value.contents
                errors = list(Draft7Validator(definition, registry=registry()).iter_errors(value))
                checks.append({'file': path, 'passed': not errors, 'errors': [e.message for e in errors]})
    return checks


def field(kind: str, prop: str) -> dict:
    return {kind: {'Expression': {'SourceRef': {'Entity': 'DemoFacts'}}, 'Property': prop}}


def projection(kind: str, prop: str) -> dict:
    return {'field': field(kind, prop), 'queryRef': 'DemoFacts.' + prop, 'nativeQueryRef': prop}


def literal(value: str) -> dict:
    return {'expr': {'Literal': {'Value': value}}}


def report_filters(filters: dict) -> dict:
    result = []
    for key, values in sorted(filters.items()):
        if not values:
            continue
        prop = DIMENSIONS[key]
        expr = {'Column': {'Expression': {'SourceRef': {'Source': 'f'}}, 'Property': prop}}
        result.append({'name': 'scope_' + key, 'type': 'Categorical', 'field': field('Column', prop),
            'filter': {'Version': 2, 'From': [{'Name': 'f', 'Entity': 'DemoFacts', 'Type': 0}],
                       'Where': [{'Condition': {'In': {'Expressions': [expr],
                           'Values': [[{'Literal': {'Value': "'" + str(v).replace("'", "''") + "'"}}] for v in values]}}}]}})
    return {'filters': result}


def demo_model() -> dict:
    data = rows()
    cols = list(data[0])
    def mvalue(value):
        return '"' + value.replace('"', '""') + '"' if isinstance(value, str) else str(value)
    m_rows = ',\n'.join('{' + ','.join(mvalue(r[c]) for c in cols) + '}' for r in data)
    types = ', '.join(c + ' = ' + ('number' if c == 'NetSalesEUR' else 'Int64.Type' if c == 'UnitsShipped' else 'text') for c in cols)
    expression = '#table(type table [' + types + '], {\n' + m_rows + '\n})'
    return {'name': 'BayerDemo', 'compatibilityLevel': 1567, 'model': {
        'culture': 'en-US', 'defaultPowerBIDataSourceVersion': 'powerBI_V3',
        'tables': [{'name': 'DemoFacts',
            'columns': [{'name': c, 'dataType': 'double' if c == 'NetSalesEUR' else 'int64' if c == 'UnitsShipped' else 'string',
                         'sourceColumn': c, 'summarizeBy': 'none'} for c in cols],
            'measures': [{'name': mid, 'expression': f"SUM('DemoFacts'[{b['column']}])", 'formatString': b['format'],
                          'description': 'Team-defined synthetic demo formula, not an executable definition supplied by Bayer.'}
                         for mid, b in BINDINGS.items()],
            'partitions': [{'name': 'DemoFacts', 'mode': 'import', 'source': {'type': 'm', 'expression': expression}}]}]}}


def render_pbip(spec: dict, out_root: Path, run_key: str) -> dict:
    binding = contract(spec)
    if not binding['supported'] or not spec.get('validation', {}).get('passed'):
        raise ValueError('Generation blocked: specification or executable bindings are incomplete.')
    if spec.get('execution_contract') != binding:
        raise ValueError('Execution contract changed. Review the exact binding before generating.')
    name = slug(spec['name'])
    root = out_root / run_key / name
    prefix = name + '.Report/'
    model_path = 'BayerDemo.SemanticModel'
    files = {
        name + '.pbip': js({'$schema': schema('fabric/pbip/pbipProperties/1.0.0'), 'version': '1.0',
                           'artifacts': [{'report': {'path': name + '.Report'}}], 'settings': {'enableAutoRecovery': True}}),
        prefix + 'definition.pbir': js({'$schema': schema('fabric/item/report/definitionProperties/2.0.0'),
            'version': '4.0', 'datasetReference': {'byPath': {'path': '../' + model_path}}}),
        prefix + 'definition/version.json': js({'$schema': schema('fabric/item/report/definition/versionMetadata/1.0.0'), 'version': '2.0.0'}),
        prefix + 'definition/report.json': js({'$schema': schema('fabric/item/report/definition/report/3.1.0'),
                                               'themeCollection': {}, 'filterConfig': report_filters(spec.get('filters', {}))}),
        model_path + '/definition.pbism': js({'$schema': schema('fabric/item/semanticModel/definitionProperties/1.0.0'), 'version': '4.0'}),
        model_path + '/model.bim': js(demo_model()),
    }
    page_names = []
    layout_checks = []
    for pi, page in enumerate(spec['pages']):
        pn = f'page{pi:02d}'
        page_names.append(pn)
        page_path = prefix + 'definition/pages/' + pn + '/'
        files[page_path + 'page.json'] = js({'$schema': schema('fabric/item/report/definition/page/2.0.0'),
            'name': pn, 'displayName': page['name'] + ' · synthetic demo', 'displayOption': 'FitToPage', 'width': 1280, 'height': 720})
        for vi, v in enumerate(page['visuals']):
            mid = v['measure']
            if mid not in binding['bindings'] or v['type'] not in VISUAL_TYPES:
                raise ValueError('Unsupported visual binding')
            by = DIMENSIONS.get(v.get('by'))
            measure = projection('Measure', mid)
            dimension = projection('Column', by) if by else None
            if v['type'] == 'table':
                state = {'Values': {'projections': ([dimension] if dimension else []) + [measure]}}
            elif v['type'] == 'card':
                state = {'Values': {'projections': [measure]}}
            else:
                if not dimension:
                    raise ValueError('Trend/breakdown requires an explicit dimension')
                state = {'Category': {'projections': [dimension]}, 'Y': {'projections': [measure]}}
            vn = f'visual{vi:02d}'
            pos = {'x': 24 + vi % 3 * 420, 'y': 40 + vi // 3 * 320, 'width': 392,
                   'height': 150 if v['type'] == 'card' else 280, 'z': vi, 'tabOrder': vi}
            layout_checks.append(pos['x'] + pos['width'] <= 1280 and pos['y'] + pos['height'] <= 720)
            query = {'queryState': state}
            if dimension:
                query['sortDefinition'] = {'sort': [{'field': field('Column', by), 'direction': 'Ascending'}]}
            files[page_path + 'visuals/' + vn + '/visual.json'] = js({
                '$schema': schema('fabric/item/report/definition/visualContainer/2.0.0'), 'name': vn, 'position': pos,
                'visual': {'visualType': VISUAL_TYPES[v['type']], 'query': query,
                    'visualContainerObjects': {'title': [{'properties': {'show': literal('true'),
                        'text': literal("'" + v['title'].replace("'", "''") + "'"),
                        'fontSize': literal('12D'), 'fontFamily': literal("'Segoe UI'")}}]}}})
    files[prefix + 'definition/pages/pages.json'] = js({'$schema': schema('fabric/item/report/definition/pagesMetadata/1.0.0'),
                                                       'pageOrder': page_names, 'activePageName': page_names[0]})
    schema_checks = validate_json_files(files)
    if not all(c['passed'] for c in schema_checks):
        raise ValueError('PBIR schema checks failed: ' + js([c for c in schema_checks if not c['passed']]))
    if not all(layout_checks):
        raise ValueError('Visual outside canvas bounds')
    hashes = {path: hashlib.sha256(content.encode()).hexdigest() for path, content in sorted(files.items())}
    manifest = {'renderer': RENDERER_VERSION, 'spec_hash': spec_digest(spec), 'binding': binding,
                'artifact_hashes': hashes, 'schema_checks': schema_checks, 'expected_values': expected_values(spec),
                'layers': {'specification': 'passed', 'json_schemas': 'passed', 'bindings': 'passed',
                           'layout_bounds': 'passed', 'reference_totals': 'calculated', 'power_bi_rendering': 'not_run',
                           'power_bi_numeric_reconciliation': 'not_run', 'publication': 'not_run'},
                'artifact_state': 'validation_pending', 'validated_in_power_bi': False}
    files.update({'validation.json': js(manifest), 'spec.json': js(spec), 'bindings.json': js(binding),
        'README.md': '# Synthetic Power BI validation package\n\nOpen the .pbip file in Power BI Desktop, refresh the embedded synthetic model and compare each visual with validation.json. Check report scope, monthly breakdowns, labels, clipping, numeric totals, and warnings. Record results against these artifact hashes. Schema checks are not runtime acceptance. No Bayer tenant connection is used. The common BayerDemo model is identical in each self-contained package for portability.\n'})
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
    return {'folder': str(root.relative_to(out_root)), 'files': [{'path': p, 'bytes': len(t.encode())} for p,t in sorted(files.items())],
            'preview': {'model': files[prefix + 'definition.pbir']}, 'thin_report_on': 'BayerDemo',
            'validation': manifest, 'validated_in_power_bi': False, 'artifact_state': 'validation_pending'}
