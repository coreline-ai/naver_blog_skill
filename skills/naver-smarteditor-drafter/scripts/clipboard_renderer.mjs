/** Pure clipboard payloads only. A native table must still be observed in UI. */
import {RENDER_POLICY,renderPlan} from './smarteditor_checks.mjs';
import {pathToFileURL} from 'node:url';
const escape=value=>value.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
function inline(step) {
  const chars=[...step.text],marks=step.marks??[];
  // renderPlan validates marks; segments close tags in reverse order even for overlaps.
  let html='',url=null,bold=false;
  for(let i=0;i<chars.length;i++) {
    const active=marks.filter(m=>m.start<=i&&i<m.end),href=active.find(m=>m.type==='link')?.url??null;
    const strong=active.some(m=>m.type==='bold');
    if(href!==url) {
      if(bold){html+='</strong>';bold=false;}
      if(url)html+='</a>';
      if(href)html+='<a href="'+escape(href)+'">';
      url=href;
    }
    if(strong!==bold){html+=strong?'<strong>':'</strong>';bold=strong;}
    if(chars[i]==='\r') {html+='<br>';if(chars[i+1]==='\n')i++;}
    else html+=chars[i]==='\n'?'<br>':escape(chars[i]);
  }
  if(bold)html+='</strong>';if(url)html+='</a>';
  return html||'<br>';
}
export function clipboardPayload(post,indices) {
  const plan=renderPlan(post);
  if(!Array.isArray(indices)||!indices.length||indices.some((n,i)=>!Number.isInteger(n)||n<0||n>=plan.steps.length||(i&&n!==indices[i-1]+1)))throw new TypeError('contiguous observed step indices required');
  const steps=indices.map(i=>plan.steps[i]);
  if(steps.length===1&&steps[0].kind==='table') {
    const t=steps[0],row=(cells,tag)=>'<tr>'+cells.map(c=>'<'+tag+'>'+escape(c).replace(/\r\n?|\n/g,'<br>')+'</'+tag+'>').join('')+'</tr>';
    return {render_policy:RENDER_POLICY,block_ids:[t.block_id],kind:'table',text:[t.columns,...t.rows].map(r=>r.join('\t')).join('\n'),
      html:'<table><thead>'+row(t.columns,'th')+'</thead><tbody>'+t.rows.map(r=>row(r,'td')).join('')+'</tbody></table>',requires_native_verification:true};
  }
  if(steps.some(s=>s.kind!=='paragraph'))throw new TypeError('quotes, media and tables require separate scoped UI operations');
  const html=[],text=[];
  for(let i=0;i<steps.length;i++) {
    if(i&&steps[i-1].block_id!==steps[i].block_id){html.push('<p><br></p>');text.push('');}
    html.push('<p>'+inline(steps[i])+'</p>');text.push(steps[i].text);
  }
  return {render_policy:RENDER_POLICY,kind:'paragraphs',block_ids:steps.map(s=>s.block_id),text:text.join('\n'),html:html.join(''),requires_layout_verification:true};
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href) {
  let input='';for await(const chunk of process.stdin)input+=chunk;
  try {const request=JSON.parse(input);process.stdout.write(JSON.stringify(clipboardPayload(request.post,request.indices))+'\n');}
  catch(error){process.stderr.write(JSON.stringify({error:error.message})+'\n');process.exitCode=2;}
}
