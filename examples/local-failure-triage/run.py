#!/usr/bin/env python3
"""Triage actual failures and rerun identical inputs after each correction."""
import importlib.util
import math
from pathlib import Path
import shlex
import sys
HERE=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('triage_support',HERE/'support.py');S=importlib.util.module_from_spec(s);s.loader.exec_module(S);E=S.E
def run(a):
    rows=S.vectors(a.seed,256 if a.profile=='nightly' else 32)
    faults=[('rtl','rtl-mismatch',dict(mutation=1)),('expected-value','expected-value-mismatch',dict(model=1)),('sva-disabled','verification-configuration',dict(sva_off=1,model=2)),('missing-tool','missing-tool',dict(missing=True)),('timeout','timeout',dict(hang=1))]
    ids=['build','normal']+[f'{name}/{step}' for name,_,_ in faults for step in ('diagnose','fixed')]
    e=E.Evidence('local-failure-triage',a,[Path(__file__),*S.inputs()],dict(rows=rows,faults=[dict(id=n,classification=c,flags=f) for n,c,f in faults]),ids);sim=S.Simulator(e)
    r,log=sim.execute('normal',rows);e.check('normal',S.good(r),r)
    for name,expected,flags in faults:
        r,log=sim.execute(name+'/failure',rows,**flags);classification=S.diagnose(r,log)
        exact=(S.detected(r,log,'TRIAGE_COMPARE') if name in ('rtl','expected-value') else True)
        e.check(name+'/diagnose',sim.built and classification==expected and exact,dict(expected=expected,observed=classification,evidence=r))
        fixed,_=sim.execute(name+'/fixed',rows);e.check(name+'/fixed',S.good(fixed),fixed)
        issue=(f'# {name}: {classification}\n\n'
          f'- 状態: この教材の既知の不具合を修正し、同一入力で再実行済み\n'
          f'- 仕様: イベントとW1Cクリアの同時受理はイベント優先、マスク中も保持\n'
          f'- 入力と版: ../../manifest.json、failure/vectors.txt\n'
          f'- 最初の失敗: failure/simulation.log、failure/execution.json\n'
          f'- 波形: failure/wave.vcd（起動不能時は生成なし）\n'
          f'- 再現コマンド: `{shlex.join(r["execution"]["command"])}`\n'
          f'- 根拠: 独立した仕様の真理値計算と実測値を比較。環境不良は実行エラーとして分類\n'
          f'- 修正: {flags} の注入を除去。fixed/execution.json、fixed/simulation.logで再検証\n'
          f'- 再発防止: この失敗分類と修正後の正常完了を固定ゲートに追加\n'
          f'- 限界: 実製品の根本原因を自動で断定するものではない。未知のエラーはunclassified\n')
        (e.out/name/'issue.md').write_text(issue)
    sim.save();return e.finish()
def main():
    p=E.parser(__doc__,'local-failure-triage');p.add_argument('--verilator',default='verilator');p.add_argument('--build-timeout',type=float,default=120)
    a=p.parse_args();E.validate(p,a)
    if not math.isfinite(a.build_timeout) or a.build_timeout<=0:p.error('positive finite build timeout required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
