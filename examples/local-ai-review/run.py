#!/usr/bin/env python3
"""Review saved bad proposals with native SVA, mutation and independent oracles."""
import importlib.util
import json
import math
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('ai_review_support',HERE.parent/'local-failure-triage/support.py');S=importlib.util.module_from_spec(s);s.loader.exec_module(S);E=S.E
REQUIREMENTS={'reset','event','clear','collision','masked-storage','irq-output'}
PROPOSALS={'missing-condition','wrong-past','vacuous-assertion','correlated-model'}
def review(proposal,record,log,mutation_record=None):
    findings=set();observed=set(proposal['requirements']);o=record['oracle'];counts=record['native'];raw_pass=record['status']=='pass' and not record['problems']
    if observed!=REQUIREMENTS:findings.add('requirement-omitted')
    if not record['sva_off'] and counts is not None and counts['cp_collision']==0:findings.add('collision-not-observed')
    if mutation_record and mutation_record['status']=='pass' and not mutation_record['problems']:findings.add('mutation-survived')
    if S.detected(record,log,'SVA_PAST') and o is not None and not o['rtl_mismatches']:findings.add('assertion-rejects-correct-rtl')
    if raw_pass and counts is not None and counts['cp_event']>0 and counts['cp_obligation']==0:findings.add('antecedent-unreachable')
    if raw_pass and o is not None and o['rtl_mismatches']:findings.add('incorrect-rtl-passed')
    if raw_pass and o is not None and o['rtl_mismatches'] and o['model_mismatches'] and o['rtl_mismatches']==o['model_mismatches']:findings.add('rtl-and-model-share-error')
    if record['sva_off']:findings.add('independent-check-disabled')
    return sorted(findings)
def run(a):
    path=HERE/'proposals.json';catalog=json.loads(path.read_text());proposals=catalog['proposals']
    if catalog['schema_version']!=1 or set(catalog['requirements'])!=REQUIREMENTS or len(proposals)!=4 or {p['id'] for p in proposals}!=PROPOSALS:raise ValueError('proposal/requirement inventory differs')
    rows=S.vectors(a.seed,256 if a.profile=='nightly' else 32)
    e=E.Evidence('local-ai-review',a,[Path(__file__),path,*S.inputs()],dict(rows=rows,proposals=proposals,requirements=sorted(REQUIREMENTS)),['build',*sorted(PROPOSALS),'corrected/normal',*[f'corrected/mutation{m}' for m in (1,2,3)],'corrected/sva-only'])
    sim=S.Simulator(e);decisions=[]
    for p in proposals:
        if set(p['flags'])-{'mutation','model','sva_mode','sva_off'} or len(p['requirements'])!=len(set(p['requirements'])):raise ValueError('invalid proposal settings')
        selected=[row for row in rows if not(row[1] and row[2])] if p['omit_collision'] else rows
        r,log=sim.execute(p['id']+'/candidate',selected,**p['flags']);mut=None
        if p['id']=='missing-condition':mut,_=sim.execute(p['id']+'/mutant',selected,mutation=1)
        findings=review(p,r,log,mut);ok=sim.built and bool(findings) and findings==sorted(p['expected_findings']) and not r['problems']
        decision=dict(id=p['id'],decision='reject' if findings else 'undetermined',findings=findings,expected_findings=p['expected_findings'],evidence=r,mutation_evidence=mut,review_method='fixed specification checks and real executions; no model API or human approval')
        decisions.append(decision);e.check(p['id'],ok,decision)
    r,_=sim.execute('corrected/normal',rows);e.check('corrected/normal',S.good(r),r)
    for m in (1,2,3):
        r,log=sim.execute(f'corrected/mutation{m}',rows,mutation=m)
        e.check(f'corrected/mutation{m}',S.detected(r,log,'TRIAGE_COMPARE') and bool(r['oracle'] and r['oracle']['rtl_mismatches']),r)
    # With the comparator off, the corrected assertion has to catch the clear-priority RTL by itself.
    r,log=sim.execute('corrected/sva-only',rows,mutation=1,model=2)
    e.check('corrected/sva-only',S.detected(r,log,'SVA_EVENT') and bool(r['oracle'] and r['oracle']['rtl_mismatches']),r)
    E.P.write_json(e.out/'review-decisions.json',decisions);sim.save();return e.finish()
def main():
    p=E.parser(__doc__,'local-ai-review');p.add_argument('--verilator',default='verilator');p.add_argument('--build-timeout',type=float,default=120)
    a=p.parse_args();E.validate(p,a)
    if not math.isfinite(a.build_timeout) or a.build_timeout<=0:p.error('positive finite build timeout required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
