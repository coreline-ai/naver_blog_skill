// Optional read-only oracle capture. No Chrome/network and no writes to the reference.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const root = process.argv[2];
if (!root) throw new Error('Pass the read-only reference root');
const side = fs.readFileSync(path.join(root, 'extension-local/sidepanel.js'), 'utf8');
const local = fs.readFileSync(path.join(root, 'extension-local/local-blog-prompt.js'), 'utf8');
function extract(source, name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(name);
  const next = source.slice(start + 1).search(/^(?:async )?function /m);
  return source.slice(start, next < 0 ? source.length : start + 1 + next);
}
const ctx = vm.createContext({BACKEND_RESEARCH_TOTAL_CHAR_LIMIT:24000,state:{topic:'',naverSearchKeyword:'',naverSearchSource:'section-blog'}});
vm.runInContext(extract(side,'normalizeNaverSearchSourceValue') + extract(side,'buildBackendResearchPayload') + extract(local,'formatResearchContext') + extract(local,'sanitizeResearchText'), ctx);
const make = (i, body) => ({rank:i,title:`참고 글 ${i}`,snippet:'검색 결과의 요약',url:`https://blog.naver.com/sample/${100+i}`,mobileUrl:`https://m.blog.naver.com/sample/${100+i}`,headings:['확인 기준','주의할 점'],content:body});
const cases = [
  {name:'empty', references:[]},
  {name:'short', references:[make(1, '  줄  간격\r\n\r\n\r\n을 확인합니다. '.repeat(12)),make(2,'비교 기준을 확인합니다. '.repeat(20))]},
  {name:'long-five', references:Array.from({length:5},(_,i)=>make(i+1,'본문 내용입니다. '.repeat(900)))},
  {name:'dense-lines', references:Array.from({length:8},(_,i)=>make(i+1,'한 줄\n'.repeat(1700)))},
  {name:'unicode', references:[make(1,'😀 여행 준비를 확인합니다. '.repeat(30))]},
];
const result=cases.map(c=>{
  const input={keyword:'여행 준비',searchSource:'section-blog',requestedReferenceCount:c.references.length,relatedKeywords:['여행 목록'],references:c.references};
  const payload=ctx.buildBackendResearchPayload(input);
  return {name:c.name,input,payload,context:ctx.formatResearchContext(payload)};
});
process.stdout.write(JSON.stringify({source_commit:'ab4c700b1c1effbe62f4f14ab3dbc272ad2ad982',source_files:Object.fromEntries([['sidepanel.js',side],['local-blog-prompt.js',local]].map(([name,value])=>[name,crypto.createHash('sha256').update(value).digest('hex')])),adapter_note:'Original extracted functions execute unchanged; state supplies unused defaults. No browser or network.',cases:result},null,2)+'\n');
