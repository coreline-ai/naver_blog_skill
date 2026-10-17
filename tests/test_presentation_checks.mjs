import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {verifyContent,renderPlan,canAdvance,verifyBlank,actionGate,quoteDecision} from '../skills/naver-smarteditor-drafter/scripts/smarteditor_checks.mjs';
import {clipboardPayload} from '../skills/naver-smarteditor-drafter/scripts/clipboard_renderer.mjs';
const fixture=n=>JSON.parse(readFileSync(new URL(`./fixtures/naver-series-workflow/${n}.json`,import.meta.url)));
const post=fixture('ui-post'),assets=fixture('ui-assets'),observation=()=>fixture('ui-observation');
const identity={environment:'simulation',target_blog:'demo-blog',content_revision:'c'.repeat(64)};
const verify=(p,o)=>verifyContent(p,assets,identity,o);
test('text-only table fallback fails even with all cell values present',()=>{
 const o=observation();o.components[3]={component_id:'ui04',kind:'paragraph',text:'항목: A\n설명: 내용',marks:[]};
 assert.equal(verify(post,o).checks.tables,false);
});
test('missing native or cell evidence is unknown and not accepted',()=>{
 for(const key of ['native','merged_cells','table_evidence_ref','columns','rows']) {
  const o=observation();delete o.components[3][key];assert.equal(verify(post,o).checks.tables,null);
 }
});
test('table headers row order blank cells multiline cells and spans are checked',()=>{
 const p=structuredClone(post),o=observation();p.blocks.find(b=>b.type==='table').rows=[['A',''],['B','둘째\n줄']];
 o.components[3].rows=[['A',''],['B','둘째\n줄']];assert.equal(verify(p,o).status,'passed');
 for(const rows of [[['B','둘째\n줄'],['A','']],[['A','공백'],['B','둘째\n줄']],[['A',''],['B','둘째 줄']],[['A','']]]) {
  const bad=structuredClone(o);bad.components[3].rows=rows;assert.equal(verify(p,bad).checks.tables,false);
 }
 const bad=structuredClone(o);bad.components[3].merged_cells=true;assert.equal(verify(p,bad).checks.tables,false);
});
test('header-only native table stays a table',()=>{
 const p=structuredClone(post),o=observation();p.blocks.find(b=>b.type==='table').rows=[];o.components[3].rows=[];
 assert.equal(renderPlan(p).steps[3].kind,'table');assert.equal(verify(p,o).status,'passed');
});
test('missing hard break fails while visual wrapping without inserted newline is allowed',()=>{
 const o=observation();o.components[0].text='첫 소제목 둘째 줄';assert.equal(verify(post,o).checks.body_order,true);
 assert.equal(verify(post,o).checks.line_breaks,false);
 const a=observation();a.components[1].visual_line_count=3;assert.equal(verify(post,a).status,'passed');
 const b=observation();b.components[1].text='본문의 중요한말';assert.equal(verify(post,b).checks.body_order,false);
});
test('word NBSP whitespace and CRLF do not erase logical newline structure',()=>{
 const o=observation();o.components[0].text='첫 소제목\r\n둘째 줄';assert.equal(verify(post,o).status,'passed');
 o.components[0].text='첫 소제목\n\n둘째 줄';assert.equal(verify(post,o).checks.line_breaks,false);
});
test('missing gap evidence is unknown zero gap fails blank spacer passes',()=>{
 const o=observation();delete o.components[7].layout_evidence_ref;assert.equal(verify(post,o).checks.paragraph_spacing,null);
 const a=observation();a.components[7].paragraph_gap_after_px=0;assert.equal(verify(post,a).checks.paragraph_spacing,false);
 const b=observation();delete b.components[7].paragraph_gap_after_px;
 b.components.splice(8,0,{component_id:'space-1',kind:'paragraph',text:'',marks:[]});assert.equal(verify(post,b).status,'passed');
});
test('link href label and actual codepoint position must agree',()=>{
 const p=structuredClone(post),o=observation();p.blocks[1].marks.push({type:'link',start:4,end:7,url:'https://example.org/a?b=1&c=2'});
 o.components[1].marks.push({type:'link',start:4,end:7,url:'https://example.org/a?b=1&c=2'});assert.equal(verify(p,o).status,'passed');
 const missing=structuredClone(o);missing.components[1].marks=missing.components[1].marks.filter(m=>m.type!=='link');assert.equal(verify(p,missing).checks.links,false);
 const wrong=structuredClone(o);wrong.components[1].marks[1].url='https://example.org/other';assert.equal(verify(p,wrong).checks.links,false);
 const shifted=structuredClone(o);shifted.components[1].marks[1].start=5;assert.equal(verify(p,shifted).checks.links,false);
 const unsafe=structuredClone(o);unsafe.components[1].marks[1].url='javascript:alert(1)';assert.notEqual(verify(p,unsafe).status,'passed');
});
test('clipboard preserves escaped href bold emoji explicit BR and block gap',()=>{
 const p={...post,blocks:[{id:'a',type:'paragraph',text:'😀 자료와\n다음',marks:[{type:'link',start:2,end:5,url:'https://example.org/?a=1&b=2'},{type:'bold',start:2,end:4}]},
  {id:'b',type:'paragraph',text:'<둘째>&',marks:[]}]};
 const clip=clipboardPayload(p,[0,1]);assert.equal(clip.html,'<p>😀 <a href="https://example.org/?a=1&amp;b=2"><strong>자료</strong>와</a><br>다음</p><p><br></p><p>&lt;둘째&gt;&amp;</p>');
 assert.equal(clip.text,'😀 자료와\n다음\n\n<둘째>&');
 assert.equal(clip.requires_layout_verification,true);
});
test('Unicode href serialization matches but destination and reserved separators remain strict',()=>{
 const p=structuredClone(post),o=observation();
 const url='https://example.org/product/블랙-쿠션/171/?q=한글#색상';
 p.blocks[1].marks.push({type:'link',start:4,end:7,url});
 o.components[1].marks.push({type:'link',start:4,end:7,url:new URL(url).href});
 const before=structuredClone(o);assert.equal(verify(p,o).status,'passed');assert.deepEqual(o,before);
 for(const changed of [url.replace('example.org','other.example'),url.replace('/171/','/224/'),url.replace('한글','다른값'),url.replace('#색상','#다름'),url.replace('https:','http:'),url.replace('/171/','%2F171/')]) {
  const wrong=structuredClone(o);wrong.components[1].marks.at(-1).url=new URL(changed).href;
  assert.equal(verify(p,wrong).checks.links,false);
 }
});
test('clipboard native table includes headers empty cells and escaped data',()=>{
 const p={...post,blocks:[{id:'t',type:'table',columns:['항목','값'],rows:[['A',''],['<B>','두\n줄']]}]};
 const clip=clipboardPayload(p,[0]);assert.match(clip.html,/<thead><tr><th>항목<\/th><th>값<\/th><\/tr><\/thead>/);
 assert.match(clip.html,/<td>A<\/td><td><\/td>/);assert.match(clip.html,/<td>&lt;B&gt;<\/td><td>두<br>줄<\/td>/);
 assert.equal(clip.requires_native_verification,true);
});
test('clipboard rejects noncontiguous steps and mixed media rather than dropping them',()=>{
 for(const indices of [[0],[1,2],[1,3],[],[999]])assert.throws(()=>clipboardPayload(post,indices));
});
test('native table action requires observed non-submit toolbar purpose',()=>{
 const auth={explicit_draft_request:true,mode:'draft',target_blog:'demo-blog'};
 const surface={coverage:'complete',evidence_ref:'mock://fresh',target_blog:'demo-blog',login_verified:true,recovery_pending:false,inflight:false,panel:'editor',
 control:{observed_id:'table',snapshot_ref:'mock://fresh',candidate_count:1,role:'button',purpose:'insert_table',is_final_submit:false}};
 assert.equal(actionGate('insert_table',surface,auth).allowed,true);surface.control.is_final_submit=true;
 assert.equal(actionGate('insert_table',surface,auth).allowed,false);
});
test('legacy pass or missing presentation check cannot advance',()=>{
 const input=verify(post,observation()),reopened=verifyContent(post,assets,identity,observation(),{scope:'reopened_verified',draftRef:'mock-draft-7'});
 const o=observation();o.title_fields[0].text='';o.components=[];
 const blank=verifyBlank(identity,o),save={...identity,save_acknowledged:true,evidence_ref:'mock://save'};
 assert.equal(canAdvance({identity,input,reopened,blank,save}).allowed,true);
 for(const field of ['tables','links','line_breaks','paragraph_spacing']) {
  const bad=structuredClone(input);delete bad.checks[field];assert.equal(canAdvance({identity,input:bad,reopened,blank,save}).allowed,false);
 }
 const old=structuredClone(input);old.expected.render_policy='smarteditor-subset/v1';assert.equal(canAdvance({identity,input:old,reopened,blank,save}).allowed,false);
});
test('quote target requires logical line structure even for skip',()=>{
 assert.equal(quoteDecision('첫\n둘','quotation_bubble',{candidate_count:1,component_id:'q',current_style:'quotation_bubble',paragraph_text:'첫 둘'}).action,'stop');
});
