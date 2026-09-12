/** Pure rendering/observation checks. No browser connection or publication API. */
import { pathToFileURL } from 'node:url';

const plain = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const text = v => typeof v === 'string';
const cp = v => [...v];
const clone = v => structuredClone(v);
const equal = (a,b) => JSON.stringify(a) === JSON.stringify(b);
const SHA = /^[a-f0-9]{64}$/;
export function normalizeText(value) {
  if (!text(value)) throw new TypeError('text must be a string');
  return value.replace(/\r\n?/g,'\n').replace(/\s+/gu,' ').trim();
}
export function codePointToUtf16(value, index) {
  if (!text(value) || !Number.isInteger(index) || index < 0 || index > cp(value).length) throw new RangeError('code-point offset out of range');
  return cp(value).slice(0,index).join('').length;
}
export function utf16ToCodePoint(value, index) {
  if (!text(value) || !Number.isInteger(index) || index < 0 || index > value.length) throw new RangeError('UTF-16 offset out of range');
  const n=cp(value.slice(0,index)).length;
  if (codePointToUtf16(value,n)!==index) throw new RangeError('offset splits a surrogate pair');
  return n;
}
function marksValid(value, marks) {
  return text(value) && Array.isArray(marks) && marks.every(m => plain(m) && ['bold','code'].includes(m.type)
    && Number.isInteger(m.start) && Number.isInteger(m.end) && m.start>=0 && m.start<m.end && m.end<=cp(value).length);
}
function styled(value,marks=[]) {
  if(!marksValid(value,marks)) throw new TypeError('invalid code-point marks');
  const chars=cp(value), result=[];
  chars.forEach((c,i) => {
    if(/\s/u.test(c)) { if(result.length && result.at(-1)[0]!==' ') result.push([' ',false]); }
    else result.push([c,marks.some(m=>m.type==='bold'&&m.start<=i&&i<m.end)]);
  });
  if(result.at(-1)?.[0]===' ') result.pop();
  return result;
}
function requirePost(post) {
  if(!plain(post)||post.schema!=='naver-post/v1'||!text(post.title)||!Array.isArray(post.blocks)||!Array.isArray(post.tags)) throw new TypeError('use a validated naver-post/v1');
}
export function renderPlan(post) {
  requirePost(post);
  const steps=[], fallbacks=[], ids=new Set();
  const paragraph=(b,value,marks=[],part='body',style='plain')=>{
    if(!marksValid(value,marks)) throw new TypeError('invalid text or marks');
    if(marks.some(m=>m.type==='code')) fallbacks.push({block_id:b.id,reason:'inline-code-as-plain-text'});
    steps.push({block_id:b.id,part,kind:'paragraph',text:value,marks:marks.filter(m=>m.type==='bold'),style});
  };
  for(const b of post.blocks) {
    if(!plain(b)||!text(b.id)||ids.has(b.id)) throw new TypeError('unique block id required');
    ids.add(b.id);
    switch(b.type) {
      case 'paragraph':paragraph(b,b.text,b.marks??[]);break;
      case 'heading':
        if(b.level===2&&b.style==='quotation_bubble') steps.push({block_id:b.id,part:'heading',kind:'quotation',text:b.text,marks:b.marks??[],style:b.style});
        else if(b.level===3&&b.style==='subtitle') {paragraph(b,b.text,b.marks??[],'heading');fallbacks.push({block_id:b.id,reason:'h3-as-paragraph'});}
        else throw new TypeError('unsupported heading style');
        break;
      case 'callout': {
        if(!['quotation_bubble','quotation_line','quotation_postit'].includes(b.style)) throw new TypeError('unsupported quote');
        const label=b.title||b.text;
        steps.push({block_id:b.id,part:'label',kind:'quotation',text:label,marks:[],style:b.style});
        if(b.title&&b.text) paragraph(b,b.text,[],'callout-body');
        break;
      }
      case 'list':
        if(!Array.isArray(b.items)||!['ordered','unordered','checklist'].includes(b.style)) throw new TypeError('unsupported list');
        b.items.forEach((item,i)=>{
          const prefix=b.style==='ordered'?`${i+1}. `:b.style==='checklist'?(item.checked?'☑ ':'☐ '):'• ';
          paragraph(b,prefix+item.text,(item.marks??[]).map(m=>({...m,start:m.start+cp(prefix).length,end:m.end+cp(prefix).length})),`item-${i}`);
        });
        fallbacks.push({block_id:b.id,reason:'list-as-prefixed-paragraphs'});break;
      case 'table':
        if(!Array.isArray(b.columns)||!Array.isArray(b.rows)) throw new TypeError('unsupported table');
        if(!b.rows.length) paragraph(b,b.columns.join(' | '),[],'table-header');
        b.rows.forEach((row,i)=>{
          if(!Array.isArray(row)||row.length!==b.columns.length) throw new TypeError('table width mismatch');
          paragraph(b,row.map((value,c)=>`${b.columns[c]}: ${value}`).join('\n'),[],`row-${i}`);
        });
        fallbacks.push({block_id:b.id,reason:'table-as-labelled-paragraphs'});break;
      case 'image':
        steps.push({block_id:b.id,part:'image',kind:'image',path:b.path,alt:b.alt??''});
        if(b.caption) paragraph(b,b.caption,[],'caption');
        break;
      case 'divider':steps.push({block_id:b.id,part:'divider',kind:'divider'});break;
      default:throw new TypeError(`unsupported block ${b.type}`);
    }
  }
  return {schema:'smarteditor-render-plan/v1',title:post.title,steps,tags:clone(post.tags),fallbacks};
}
function observedComplete(observation) {
  return plain(observation)&&observation.schema==='smarteditor-observation/v1'
    &&['live','simulation'].includes(observation.environment)&&text(observation.evidence_ref)&&!!observation.evidence_ref
    &&text(observation.observed_at)&&Number.isFinite(Date.parse(observation.observed_at))
    &&observation.coverage==='complete'&&observation.body_root_observed===true
    &&Array.isArray(observation.title_fields)&&observation.title_fields.length===1
    &&observation.title_fields.every(f=>plain(f)&&text(f.component_id)&&!!f.component_id&&text(f.text))
    &&Array.isArray(observation.components)&&observation.components.every(c=>plain(c)&&text(c.component_id)&&!!c.component_id&&text(c.kind))
    &&new Set(observation.components.map(c=>c.component_id)).size===observation.components.length
    &&Array.isArray(observation.unsupported_components)&&observation.unsupported_components.length===0
    &&observation.recovery_pending===false&&Array.isArray(observation.inflight_operations);
}
function baseEvidence(identity,observation,scope,expected) {
  if(!plain(identity)||!['live','simulation'].includes(identity.environment)||!SHA.test(identity.content_revision)||!text(identity.target_blog)) throw new TypeError('explicit execution identity required');
  return {schema:'smarteditor-verification/v1',scope,environment:identity.environment,target_blog:identity.target_blog,
    content_revision:identity.content_revision,expected,observed:plain(observation)?clone(observation):null,
    evidence_ref:plain(observation)?observation.evidence_ref??null:null,checks:{},status:'unknown',issues:[]};
}
function finish(result) {
  const values=Object.values(result.checks);
  result.status=values.some(v=>v===false)?'failed':values.some(v=>v===null)?'unknown':'passed';
  result.issues=Object.entries(result.checks).filter(([,v])=>v!==true).map(([name,v])=>`${name}:${v===null?'unobserved':'mismatch'}`);
  return result;
}
export function verifyBlank(identity,observation,{scope='blank_verified'}={}) {
  if(!['editor_checked','blank_verified'].includes(scope)) throw new TypeError('invalid blank scope');
  const result=baseEvidence(identity,observation,scope,{blank:true});
  const complete=observedComplete(observation);
  result.checks.complete_observation=complete?true:null;
  result.checks.target_blog=plain(observation)&&text(observation.target_blog)?observation.target_blog===identity.target_blog:null;
  result.checks.environment=plain(observation)&&text(observation.environment)?observation.environment===identity.environment:null;
  if(!complete) {result.checks.blank_editor=null;return finish(result);}
  result.checks.blank_editor=normalizeText(observation.title_fields[0].text)===''
    &&observation.inflight_operations.length===0
    &&observation.components.every(c=>c.kind==='paragraph'&&text(c.text)&&normalizeText(c.text)===''&&Array.isArray(c.marks)&&c.marks.length===0);
  return finish(result);
}
function relevantComponents(observation) {
  return observation.components.filter(c=>!(c.kind==='paragraph'&&text(c.text)&&normalizeText(c.text)===''&&Array.isArray(c.marks)&&c.marks.length===0));
}
function nearestText(steps,index,direction) {
  for(let i=index+direction;i>=0&&i<steps.length;i+=direction) if(text(steps[i].text)&&normalizeText(steps[i].text)) return normalizeText(steps[i].text);
  return null;
}
export function verifyContent(post,assets,identity,observation,{scope='input_verified',draftRef=null}={}) {
  if(!['input_verified','reopened_verified'].includes(scope)) throw new TypeError('invalid content scope');
  const plan=renderPlan(post), result=baseEvidence(identity,observation,scope,plan);
  if(!Array.isArray(assets)||assets.some(a=>!plain(a)||!text(a.path)||!SHA.test(a.sha256))||new Set(assets.map(a=>a.path)).size!==assets.length) throw new TypeError('validated asset records required');
  const byPath=new Map(assets.map(a=>[a.path,a]));
  for(const step of plan.steps) if(step.kind==='image'&&!byPath.has(step.path)) throw new TypeError('asset integrity missing');
  const complete=observedComplete(observation);
  result.checks={complete_observation:complete?true:null,environment:plain(observation)?observation.environment===identity.environment:null,
    target_blog:plain(observation)&&text(observation.target_blog)?observation.target_blog===identity.target_blog:null,
    title:null,body_order:null,image_order:null,image_anchors:null,tags:null,formatting:null};
  if(scope==='reopened_verified') {result.checks.draft_identity=null;result.checks.no_inflight_operation=null;}
  if(!complete) return finish(result);
  const actual=relevantComponents(observation), expected=plan.steps;
  result.checks.title=normalizeText(observation.title_fields[0].text)===normalizeText(plan.title);
  result.checks.no_inflight_operation=observation.inflight_operations.length===0;
  let body=true,format=true,imageOrder=true,anchors=true;
  if(actual.length!==expected.length) body=imageOrder=anchors=format=false;
  for(let i=0;i<expected.length&&i<actual.length;i++) {
    const want=expected[i],got=actual[i];
    if(want.kind!==got.kind) {body=format=false;if(want.kind==='image'||got.kind==='image') imageOrder=anchors=false;continue;}
    if(text(want.text)) {
      if(!text(got.text)) {body=null;format=null;}
      else {
        if(normalizeText(want.text)!==normalizeText(got.text)) body=false;
        if(!Array.isArray(got.marks)||!marksValid(got.text,got.marks)) format=null;
        else if(!equal(styled(want.text,want.marks??[]),styled(got.text,got.marks))) format=false;
        if(want.kind==='quotation') {
          if(!text(got.style)) format=null;
          else if(got.style!==want.style) format=false;
        }
      }
    }
    if(want.kind==='image') {
      if(got.loaded!==true) imageOrder=got.loaded===false?false:null;
      if(!text(got.asset_sha256)||!SHA.test(got.asset_sha256)||!text(got.asset_evidence_ref)||!got.asset_evidence_ref) imageOrder=null;
      else if(got.asset_sha256!==byPath.get(want.path).sha256) imageOrder=false;
      if(nearestText(actual,i,-1)!==nearestText(expected,i,-1)||nearestText(actual,i,1)!==nearestText(expected,i,1)) anchors=false;
    }
  }
  result.checks.body_order=body;result.checks.formatting=format;result.checks.image_order=imageOrder;result.checks.image_anchors=anchors;
  if(observation.tags_observed===true&&Array.isArray(observation.tags)&&observation.tags.every(text)) {
    const tags=observation.tags;
    result.checks.tags=new Set(tags).size===tags.length&&equal([...tags].sort(),[...plan.tags].sort())
      &&cp(tags.map(t=>'#'+t).join(' ')).length<=100&&!tags.some(t=>/\s|#/u.test(t));
  }
  if(scope==='reopened_verified') {
    const observed=observation.draft_identity;
    if(plain(observed)&&text(observed.reference)&&observed.matched_unique===true&&text(observed.evidence_ref)&&observed.evidence_ref&&text(draftRef)&&draftRef) result.checks.draft_identity=observed.reference===draftRef;
  }
  return finish(result);
}
export function quoteDecision(targetText,style,selection) {
  if(!text(targetText)||!['quotation_bubble','quotation_line','quotation_postit'].includes(style)) throw new TypeError('invalid quote target');
  const stop=reason=>({status:'failed',action:'stop',reason});
  if(!plain(selection)||selection.candidate_count!==1||!text(selection.component_id)||!selection.component_id) return stop('original-selector-not-unique');
  if(!text(selection.paragraph_text)||normalizeText(selection.paragraph_text)!==normalizeText(targetText)) return stop('paragraph-does-not-match');
  if(!['plain','quotation_bubble','quotation_line','quotation_postit'].includes(selection.current_style)) return stop('current-style-unobserved');
  if(selection.current_style===style) return {status:'passed',action:'skip',reason:'already-styled'};
  if(!text(selection.text)||normalizeText(selection.text)!==normalizeText(targetText)||selection.start!==0||selection.end!==cp(selection.paragraph_text).length) return stop('full-paragraph-not-selected');
  return {status:'passed',action:'apply',style};
}
const ACTIONS={
  insert_block:['editor','textbox','edit_body'],upload_image:['editor','button','upload_image'],apply_quote:['selection','button','apply_quote'],
  open_tag_settings:['editor','button','open_tag_settings'],close_tag_settings:['publish_settings','button','close_tag_settings'],
  input_tags:['publish_settings','textbox','input_tags'],save:['editor','button','save_draft'],
  open_saved:['draft_list','button','open_saved_draft'],new_editor:['editor','button','new_editor']
};
export function actionGate(action,surface,authorization) {
  const deny=reason=>({allowed:false,reason});
  if(!Object.hasOwn(ACTIONS,action)) return deny('operation-not-allowed');
  if(!plain(authorization)||!text(authorization.target_blog)||!authorization.target_blog||authorization.explicit_draft_request!==true||!['draft','resume'].includes(authorization.mode)) return deny('explicit-draft-authorization-required');
  if(!plain(surface)||surface.coverage!=='complete'||!text(surface.evidence_ref)||!surface.evidence_ref||surface.target_blog!==authorization.target_blog||surface.login_verified!==true||surface.recovery_pending!==false||surface.inflight!==false) return deny('surface-unverified');
  const c=surface.control,[panel,role,purpose]=ACTIONS[action];
  if(!plain(c)||c.candidate_count!==1||!text(c.observed_id)||!c.observed_id||c.snapshot_ref!==surface.evidence_ref||c.is_final_submit!==false) return deny('control-unverified-or-submit');
  if(surface.panel!==panel||c.role!==role||c.purpose!==purpose) return deny('ambiguous-control-purpose');
  return {allowed:true,reason:'scoped-observed-control',observed_id:c.observed_id};
}
export async function guardedAction(action,surface,authorization,perform) {
  const gate=actionGate(action,surface,authorization);
  if(!gate.allowed) return gate;
  if(typeof perform!=='function') throw new TypeError('trusted tool binding required');
  return {allowed:true,result:await perform(gate.observed_id)};
}
export function canAdvance({identity,input,save,reopened,blank}) {
  const reasons=[];
  const required={input:['complete_observation','environment','target_blog','title','body_order','image_order','image_anchors','tags','formatting','no_inflight_operation'],reopened:['complete_observation','environment','target_blog','title','body_order','image_order','image_anchors','tags','formatting','no_inflight_operation','draft_identity'],blank:['complete_observation','target_blog','environment','blank_editor']};
  for(const [name,value,scope] of [['input',input,'input_verified'],['reopened',reopened,'reopened_verified'],['blank',blank,'blank_verified']]) {
    if(!plain(value)||value.status!=='passed'||value.scope!==scope||!plain(value.checks)||!Object.keys(value.checks).length
      ||Object.values(value.checks).some(v=>v!==true)||required[name].some(k=>value.checks[k]!==true)||value.environment!==identity.environment||value.target_blog!==identity.target_blog
      ||value.content_revision!==identity.content_revision||!value.evidence_ref||!plain(value.observed)) reasons.push(name+'-not-verified');
  }
  // Recovery can prove an existing saved draft by a full, recorded reconciliation.
  // Do not relabel a missing original toast as an observed acknowledgment.
  const saved=plain(save)&&(save.save_acknowledged===true || (save.saved_reconciled===true
    &&plain(reopened)&&save.reconciliation_evidence_ref===reopened.evidence_ref&&!!reopened.evidence_ref));
  if(!saved||!save.evidence_ref||save.environment!==identity.environment||save.target_blog!==identity.target_blog||save.content_revision!==identity.content_revision) reasons.push('save-not-acknowledged-or-reconciled');
  return {allowed:reasons.length===0,reasons};
}
export function evaluate(request) {
  switch(request.command) {
    case 'render_plan':return renderPlan(request.post);
    case 'verify_content':return verifyContent(request.post,request.assets,request.identity,request.observation,request.options);
    case 'verify_blank':return verifyBlank(request.identity,request.observation,request.options);
    case 'quote_decision':return quoteDecision(request.target_text,request.style,request.selection);
    case 'action_gate':return actionGate(request.action,request.surface,request.authorization);
    case 'can_advance':return canAdvance(request);
    default:throw new TypeError('unknown local check command');
  }
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href) {
  let data='';for await(const chunk of process.stdin) data+=chunk;
  try {process.stdout.write(JSON.stringify(evaluate(JSON.parse(data)))+'\n');}
  catch(error) {process.stderr.write(JSON.stringify({error:error.message})+'\n');process.exitCode=2;}
}
