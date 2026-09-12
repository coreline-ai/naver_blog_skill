import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {renderPlan,verifyBlank,verifyContent,quoteDecision,codePointToUtf16,utf16ToCodePoint,actionGate,guardedAction,canAdvance} from '../skills/naver-smarteditor-drafter/scripts/smarteditor_checks.mjs';
const fixture=name=>JSON.parse(readFileSync(new URL(`./fixtures/naver-series-workflow/${name}.json`,import.meta.url),'utf8'));
const post=fixture('ui-post'),assets=fixture('ui-assets');
const observed=()=>fixture('ui-observation');
const identity={environment:'simulation',target_blog:'demo-blog',content_revision:'c'.repeat(64)};
const verify=o=>verifyContent(post,assets,identity,o);
const blank=()=>({...observed(),title_fields:[{component_id:'title',text:''}],components:[{component_id:'empty',kind:'paragraph',text:'',marks:[]}],tags:[]});
const authorization={explicit_draft_request:true,mode:'draft',target_blog:'demo-blog'};
const surface=()=>({coverage:'complete',evidence_ref:'mock://fresh',target_blog:'demo-blog',login_verified:true,recovery_pending:false,inflight:false,panel:'editor',control:{observed_id:'toolbar-4',snapshot_ref:'mock://fresh',candidate_count:1,role:'button',purpose:'open_tag_settings',is_final_submit:false,label:'발행'}});

test('independent canonical and observed fixtures agree including all formatting',()=>{
 const result=verify(observed());assert.equal(result.status,'passed');assert.equal(result.observed.components[0].component_id,'ui01');
 assert.equal(result.expected.steps[0].block_id,'b1');assert.equal(result.expected.steps.length,12);
});
test('render plan splits summary label from body and prefixes marks correctly',()=>{
 const plan=renderPlan(post);assert.equal(plan.steps[6].kind,'quotation');assert.equal(plan.steps[7].kind,'paragraph');
 assert.equal(plan.steps[7].text,'요약 설명');assert.deepEqual(plan.steps[4].marks,[{start:3,end:5,type:'bold'}]);
 assert.deepEqual(plan.fallbacks.map(f=>f.reason),['table-as-labelled-paragraphs','list-as-prefixed-paragraphs','h3-as-paragraph']);
});
test('NBSP and visual paragraph line wrapping compare without mutating input',()=>{
 const o=observed(),before=JSON.stringify(o);assert.equal(verify(o).checks.title,true);assert.equal(JSON.stringify(o),before);
});
test('empty paragraph plus hidden nonempty paragraph is not a blank editor',()=>{
 const o=blank();o.components.push({component_id:'hidden',kind:'paragraph',text:'기존 비공개 원고',marks:[],visible:false});
 assert.equal(verifyBlank(identity,o).checks.blank_editor,false);
});
test('quotation image divider and unknown component cannot be blank',()=>{
 for(const kind of ['quotation','image','divider','unknown']) {const o=blank();o.components.push({component_id:'extra',kind,text:'',marks:[]});assert.equal(verifyBlank(identity,o).status,'failed');}
});
test('partial or missing body coverage is unknown rather than blank',()=>{
 for(const patch of [{coverage:'partial'},{body_root_observed:false},{components:null},{recovery_pending:true},{unsupported_components:['video']}]) {
  const result=verifyBlank(identity,{...blank(),...patch});assert.notEqual(result.status,'passed');assert.equal(result.checks.blank_editor,null);
 }
});
test('blank requires no title and no active operation',()=>{
 assert.equal(verifyBlank(identity,blank()).status,'passed');
 const a=blank();a.title_fields[0].text='기존 제목';assert.equal(verifyBlank(identity,a).status,'failed');
 const b=blank();b.inflight_operations=['upload:live-handle'];assert.equal(verifyBlank(identity,b).status,'failed');
});
test('missing middle paragraph fails even with matching first last and media count',()=>{
 const o=observed();o.components.splice(3,1);const r=verify(o);assert.equal(r.status,'failed');assert.equal(r.checks.body_order,false);
});
test('same image count but changed order fails',()=>{
 const o=observed();[o.components[2],o.components[9]]=[o.components[9],o.components[2]];
 assert.equal(verify(o).checks.image_order,false);
});
test('same text set but different image position fails anchors',()=>{
 const o=observed();[o.components[2],o.components[3]]=[o.components[3],o.components[2]];
 const r=verify(o);assert.equal(r.status,'failed');assert.equal(r.checks.image_anchors,false);
});
test('unidentified or still loading image never passes',()=>{
 for(const patch of [{asset_sha256:null},{asset_evidence_ref:null},{loaded:false},{loaded:null}]) {
  const o=observed();Object.assign(o.components[2],patch);assert.notEqual(verify(o).status,'passed');
 }
});
test('count-only observation cannot prove full contents',()=>{
 const o={...observed(),components:undefined,image_count:2};assert.equal(verify(o).status,'unknown');
});
test('lost tag and tags not actually observed are distinct failures',()=>{
 const o=observed();o.tags=['테스트'];assert.equal(verify(o).checks.tags,false);
 o.tags=null;o.tags_observed=false;assert.equal(verify(o).checks.tags,null);
});
test('duplicate tag or raw # text is rejected',()=>{
 for(const tags of [['검증','검증'],['#검증','테스트']]) {const o=observed();o.tags=tags;assert.equal(verify(o).checks.tags,false);}
});
test('missing bold or wrong quotation style fails formatting',()=>{
 const o=observed();o.components[1].marks=[];assert.equal(verify(o).checks.formatting,false);
 const p=observed();p.components[6].style='quotation_bubble';assert.equal(verify(p).checks.formatting,false);
});
test('reopen needs unique observed draft reference, not just save toast',()=>{
 const o=observed();assert.equal(verifyContent(post,assets,identity,o,{scope:'reopened_verified',draftRef:'mock-draft-7'}).status,'passed');
 for(const d of [null,{reference:'mock-draft-7',matched_unique:false,evidence_ref:'mock://ambiguous'}]) {
  o.draft_identity=d;o.save_acknowledged=true;assert.notEqual(verifyContent(post,assets,identity,o,{scope:'reopened_verified',draftRef:'mock-draft-7'}).status,'passed');
 }
});
test('live observation cannot be passed as simulated or vice versa',()=>{
 const o=observed();o.environment='live';assert.equal(verify(o).status,'failed');
});
test('codepoint/UTF16 conversion preserves emoji and rejects split surrogate',()=>{
 assert.equal(codePointToUtf16('A😀한',2),3);assert.equal(utf16ToCodePoint('A😀한',3),2);
 assert.throws(()=>utf16ToCodePoint('A😀한',2),RangeError);assert.throws(()=>codePointToUtf16('x',4),RangeError);
});
test('quote selection requires original selector uniqueness before first()',()=>{
 const s={candidate_count:2,component_id:'x',paragraph_text:'소제목',text:'소제목',start:0,end:3};
 assert.equal(quoteDecision('소제목','quotation_bubble',s).action,'stop');
});
test('quote full multiline selection is required',()=>{
 const full='첫 소제목\n둘째 줄';const s={candidate_count:1,component_id:'x',current_style:'plain',paragraph_text:full,text:'첫 소제목',start:0,end:5};
 assert.equal(quoteDecision(full,'quotation_bubble',s).action,'stop');
 s.text=full;s.end=[...full].length;assert.equal(quoteDecision(full,'quotation_bubble',s).action,'apply');
});
test('already styled quote is not converted again',()=>{
 const s={candidate_count:1,component_id:'x',paragraph_text:'핵심 요약',current_style:'quotation_line'};
 assert.equal(quoteDecision('핵심 요약','quotation_line',s).action,'skip');
});
test('publication is denied even when label matches an allowed settings entry',async()=>{
 let calls=0;const perform=()=>calls++;
 const s=surface();assert.equal((await guardedAction('open_tag_settings',s,authorization,perform)).allowed,true);
 s.panel='publish_settings';s.control.purpose='publish_submit';s.control.is_final_submit=true;
 assert.equal((await guardedAction('open_tag_settings',s,authorization,perform)).allowed,false);
 assert.equal((await guardedAction('publish',s,authorization,perform)).allowed,false);assert.equal(calls,1);
});
test('prepare status untrusted authorization stale selectors and ambiguous buttons do not call tools',async()=>{
 let calls=0;
 for(const mode of ['prepare','status']) assert.equal((await guardedAction('open_tag_settings',surface(),{...authorization,mode},()=>calls++)).allowed,false);
 for(const patch of [{snapshot_ref:'old'},{candidate_count:2},{is_final_submit:null},{purpose:'unknown'}]) {
  const s=surface();Object.assign(s.control,patch);assert.equal((await guardedAction('open_tag_settings',s,authorization,()=>calls++)).allowed,false);
 }
 assert.equal(calls,0);
});
test('next episode requires input ack reopen and blank for the same revision',()=>{
 const input=verify(observed()),reopened=verifyContent(post,assets,identity,observed(),{scope:'reopened_verified',draftRef:'mock-draft-7'}),empty=verifyBlank(identity,blank());
 const save={...identity,save_acknowledged:true,evidence_ref:'mock://save'};
 assert.equal(canAdvance({identity,input,reopened,blank:empty,save}).allowed,true);
 for(const patch of [{save:null},{reopened:null},{blank:null},{reopened:{...reopened,status:'unknown'}},{blank:{...empty,content_revision:'d'.repeat(64)}}])
  assert.equal(canAdvance({identity,input,reopened,blank:empty,save,...patch}).allowed,false);
});
test('CLI performs JSON checks without browser or filesystem outputs',()=>{
 const script=new URL('../skills/naver-smarteditor-drafter/scripts/smarteditor_checks.mjs',import.meta.url);
 const r=spawnSync(process.execPath,[script.pathname],{input:JSON.stringify({command:'verify_content',post,assets,identity,observation:observed()}),encoding:'utf8'});
 assert.equal(r.status,0,r.stderr);assert.equal(JSON.parse(r.stdout).status,'passed');
});

test('unobserved quote style and forged minimal success do not advance',()=>{
 const s={candidate_count:1,component_id:'x',paragraph_text:'제목',text:'제목',start:0,end:2};
 assert.equal(quoteDecision('제목','quotation_bubble',s).action,'stop');
 const fake={...identity,status:'passed',scope:'input_verified',checks:{invented:true},observed:{some:'text'},evidence_ref:'mock://forged'};
 assert.equal(canAdvance({identity,input:fake,save:{...identity,save_acknowledged:true,evidence_ref:'mock://ack'},reopened:{...fake,scope:'reopened_verified'},blank:{...fake,scope:'blank_verified'}}).allowed,false);
});

test('missing save ack can advance only with the same fully reopened reconciliation evidence',()=>{
 const input=verify(observed()),reopened=verifyContent(post,assets,identity,observed(),{scope:'reopened_verified',draftRef:'mock-draft-7'}),empty=verifyBlank(identity,blank());
 const save={...identity,save_acknowledged:false,saved_reconciled:true,evidence_ref:'mock://event-reconciled-saved',reconciliation_evidence_ref:reopened.evidence_ref};
 assert.equal(canAdvance({identity,input,reopened,blank:empty,save}).allowed,true);
 assert.equal(canAdvance({identity,input,reopened,blank:empty,save:{...save,reconciliation_evidence_ref:'unrelated'}}).allowed,false);
 assert.equal(canAdvance({identity,input,reopened:{...reopened,status:'unknown'},blank:empty,save}).allowed,false);
 assert.equal(canAdvance({identity,input,reopened,blank:empty,save:{...save,saved_reconciled:false}}).allowed,false);
});

test('expired login wrong account recovery popup partial surface and inflight uploads call no action',async()=>{
 let calls=0;
 for(const patch of [{login_verified:false},{login_verified:null},{target_blog:'different-blog'},{recovery_pending:true},{coverage:'partial'},{inflight:true}]) {
  assert.equal((await guardedAction('open_tag_settings',{...surface(),...patch},authorization,()=>calls++)).allowed,false);
 }
 assert.equal(calls,0);
});
