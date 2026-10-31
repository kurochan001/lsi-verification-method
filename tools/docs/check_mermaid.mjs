import fs from 'node:fs';
import {JSDOM} from 'jsdom';
const [input,output]=process.argv.slice(2);
if(!input||!output||process.argv.length!==4)throw Error('usage: node check_mermaid.mjs blocks.json result.json');
const dom=new JSDOM('<!doctype html><html><body></body></html>');
globalThis.window=dom.window;globalThis.document=dom.window.document;
const {default:mermaid}=await import('mermaid');
mermaid.initialize({startOnLoad:false,securityLevel:'strict'});
const blocks=JSON.parse(fs.readFileSync(input,'utf8'));const results=[];
if(!Array.isArray(blocks))throw Error('diagram inventory must be an array');
for(const block of blocks){
 if(typeof block.id!=='string'||typeof block.source!=='string'||!block.source.trim())throw Error('invalid diagram record');
 try{await mermaid.parse(block.source);results.push({id:block.id,success:true});}
 catch(error){results.push({id:block.id,success:false,message:String(error)});}
}
fs.writeFileSync(output,JSON.stringify({success:results.every(r=>r.success),results},null,2)+'\n');
process.exitCode=results.every(r=>r.success)?0:1;
