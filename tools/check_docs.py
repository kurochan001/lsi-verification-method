#!/usr/bin/env python3
"""Check tracked Markdown links, structure, glossary/FAQ and real Mermaid syntax."""
import argparse
from datetime import datetime,timezone
from html.parser import HTMLParser
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
from urllib.parse import unquote,urlsplit
import quality_common as Q
HERE=Path(__file__).resolve().parent
def inventory(root):
    r=subprocess.run(['git','-C',str(root),'ls-files','-z','--cached','--others','--exclude-standard'],capture_output=True,check=True)
    return sorted(set(p.decode() for p in r.stdout.split(b'\0') if p))
def slug(text):return ''.join(c for c in text.lower() if c in '-_ ' or not unicodedata.category(c).startswith(('P','S'))).replace(' ','-')
class Page(HTMLParser):
    def __init__(self):
        super().__init__();self.links=[];self.ids=set();self.headings=[];self.heading=None;self.code=0;self.tables=[];self.row=None;self.cell=None;self.table=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ('code','pre'):self.code+=1
        if not self.code:
            self.links += [a[k] for k in ('href','src') if k in a]
        if 'id' in a:self.ids.add(a['id'])
        if tag=='a' and 'name' in a:self.ids.add(a['name'])
        if re.fullmatch(r'h[1-6]',tag):self.heading=[]
        if tag=='table':self.table=[]
        if tag=='tr' and self.table is not None:self.row=[]
        if tag in ('td','th') and self.row is not None:self.cell=[]
    def handle_data(self,data):
        if self.heading is not None:self.heading.append(data)
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if re.fullmatch(r'h[1-6]',tag) and self.heading is not None:self.headings.append(''.join(self.heading));self.heading=None
        if tag in ('code','pre'):self.code=max(0,self.code-1)
        if tag in ('td','th') and self.cell is not None:self.row.append(''.join(self.cell).strip());self.cell=None
        if tag=='tr' and self.row is not None:self.table.append(self.row);self.row=None
        if tag=='table' and self.table is not None:self.tables.append(self.table);self.table=None
    def anchors(self):
        used=set()
        for heading in self.headings:
            base=slug(heading);name=base;n=0
            while name in used:n+=1;name=base+'-'+str(n)
            used.add(name)
        return self.ids|used
def structure(raw,name):
    errors=[];blocks=[];fence=None;start=0;lines=[];columns=None
    for number,line in enumerate(raw.splitlines(),1):
        f=re.match(r'^\s{0,3}(`{3,}|~{3,})(.*)$',line)
        if f:
            if fence is None:
                fence=(f[1],f[2].strip());start=number;lines=[];columns=None
            elif f[1][0]==fence[0][0] and len(f[1])>=len(fence[0]) and not f[2].strip():
                if fence[1]=='mermaid':blocks.append(dict(id=f'{name}:{start}',file=name,line=start,source='\n'.join(lines)))
                fence=None
            elif fence is not None:lines.append(line)
            continue
        if fence is not None:lines.append(line);continue
        if line.lstrip().startswith('|'):
            count=len(re.findall(r'(?<!\\)\|',line))-1
            if columns is None:columns=count
            elif columns!=count:errors.append(dict(line=number,error='table column count differs'))
        else:columns=None
    if fence is not None:errors.append(dict(line=start,error='unclosed code fence'))
    return errors,blocks
def glossary(page):
    terms=[r[0] for t in page.tables if t and t[0] and t[0][0]=='用語' for r in t[1:] if r]
    if not terms or any(not term for term in terms) or len(terms)!=len(set(terms)):raise ValueError('empty/duplicate glossary term')
    return len(terms)
def faq(page):
    q=[int(m[1]) for h in page.headings if (m:=re.match(r'^Q(\d+)\.',h))]
    if not q or q!=list(range(1,len(q)+1)):raise ValueError('FAQ numbers must be unique and consecutive from Q1')
    return len(q)
def run(a):
    import markdown
    root=a.root.resolve();files=inventory(root);names=[n for n in files if n.lower().endswith('.md')]
    if not names:raise ValueError('no Markdown documents')
    pages={};problems={};blocks=[];read_hashes={};inputs=[Path(__file__),HERE/'docs-requirements.txt',HERE/'docs/package.json',HERE/'docs/package-lock.json',HERE/'docs/check_mermaid.mjs']
    for name in names:
        path=root/name;inputs.append(path);content=path.read_bytes();read_hashes[name]=hashlib.sha256(content).hexdigest();raw=content.decode('utf-8');p=Page();p.feed(markdown.markdown(raw,extensions=['fenced_code','tables']));pages[name]=p
        errors,diagrams=structure(raw,name);problems[name]=errors;blocks+=diagrams
    if len({b['id'] for b in blocks})!=len(blocks):raise ValueError('duplicate diagram identity')
    link_count=heading_count=0
    for name,page in pages.items():
        for href in page.links:
            u=urlsplit(href)
            if u.scheme or u.netloc:continue
            link_count+=1;target=(root/name).parent/unquote(u.path) if u.path else root/name;target=target.resolve()
            if not target.is_relative_to(root):problems[name].append(dict(link=href,error='link escapes repository'));continue
            relative=str(target.relative_to(root))
            listed=relative in files or target.is_dir() and (relative=='.' or any(n.startswith(relative+'/') for n in files))
            if not target.exists() or not listed:problems[name].append(dict(link=href,error='missing/untracked target'));continue
            if target.is_file():inputs.append(target)
            if u.fragment and target.suffix.lower()=='.md':
                heading_count+=1
                if relative not in pages or unquote(u.fragment) not in pages[relative].anchors():problems[name].append(dict(link=href,error='missing heading/anchor'))
    checks=['inventory',*['document/'+n for n in names],'glossary','faq','mermaid-runtime',*['diagram/'+b['id'] for b in blocks],'source-freshness']
    report=Q.Report('documentation',a.out,inputs,checks,dict(root=str(root),node=a.node,timeout=a.timeout,documents=names,diagrams=blocks))
    report.check('inventory',True,dict(documents=len(names),local_links=link_count,heading_links=heading_count))
    for name in names:report.check('document/'+name,not problems[name],problems[name])
    counts={}
    for name,check in [('docs/glossary.md',glossary),('docs/faq.md',faq)]:
        identity='glossary' if 'glossary' in name else 'faq'
        try:counts[identity]=check(pages[name]);report.check(identity,True,dict(items=counts[identity]))
        except (ValueError,KeyError) as exc:report.check(identity,False,str(exc))
    Q.write(report.out/'mermaid-blocks.json',blocks)
    execution=Q.P.execute([a.node,str(HERE/'docs/check_mermaid.mjs'),str(report.out/'mermaid-blocks.json'),str(report.out/'mermaid.json')],report.out/'mermaid.log',a.timeout,root)
    result={};runtime_ok=False
    try:
        result=json.loads((report.out/'mermaid.json').read_text());rows=result['results'];expected=[b['id'] for b in blocks]
        if not isinstance(rows,list) or [r['id'] for r in rows]!=expected or any(type(r['success']) is not bool for r in rows):raise ValueError('diagram result inventory differs')
        success=all(r['success'] for r in rows)
        runtime_ok=not execution['error'] and execution['returncode']==(0 if success else 1) and result['success'] is success
    except (OSError,ValueError,KeyError,TypeError) as exc:result=dict(error=str(exc),results=[])
    report.check('mermaid-runtime',runtime_ok,dict(execution=execution,result_error=result.get('error')))
    results={r['id']:r for r in result.get('results',[])}
    for block in blocks:
        r=results.get(block['id'],{});report.check('diagram/'+block['id'],runtime_ok and r.get('success') is True,r)
    changed=report.fresh()
    changed += ['document changed before input snapshot: '+name for name,h in read_hashes.items() if report.sources[str(root/name)]!=h]
    changed+=['Markdown inventory changed'] if [n for n in inventory(root) if n.lower().endswith('.md')]!=names else []
    report.check('source-freshness',not changed,changed)
    Q.write(report.out/'documentation-check.json',dict(counts=dict(documents=len(names),tables=sum(len(p.tables) for p in pages.values()),mermaid=len(blocks),local_links=link_count,heading_links=heading_count,**counts),errors={n:e for n,e in problems.items() if e},document_read_sha256=read_hashes))
    return report.finish()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Q.ROOT);p.add_argument('--node',default='node');p.add_argument('--timeout',type=float,default=120);p.add_argument('--out',type=Path,default=Q.ROOT/'artifacts'/datetime.now(timezone.utc).strftime('docs-%Y%m%dT%H%M%S%fZ'))
    a=p.parse_args()
    if not math.isfinite(a.timeout) or a.timeout<=0 or a.out.exists():p.error('positive finite timeout and fresh --out required')
    a.node=Q.executable(a.node)
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError,ImportError,subprocess.SubprocessError) as exc:print('DOCS_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
