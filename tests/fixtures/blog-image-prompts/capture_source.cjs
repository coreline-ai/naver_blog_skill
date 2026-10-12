// Optional golden-fixture capture. Reads the reference tree; never loads Chrome or writes it.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const root = process.argv[2];
if (!root) throw new Error('Pass the read-only sns_content_writer root');
const source = fs.readFileSync(path.join(root, 'extension-local/sidepanel.js'), 'utf8');
const names = ['normalizeBlogPlainText','splitBlogSentences','isBlogSentenceBoundary',
  'normalizeImagePromptComparableText','normalizeImagePromptEntry','isRepresentativeImagePromptEntry',
  'normalizeAutoImageStyleValue','normalizeArticleTypeValue','normalizeFormatPresetValue','resolveFormatPresetValue',
  'extractHeadingTexts','extractMaxNumberedSection','analyzeAutoImageStructure','analyzeAutoImageUpperBound',
  'getAutoImageUpperBound','getAutoImageUpperBoundFromHtml','getDefaultAutoImageCount',
  'resolveRequestedAutoImageCount','deriveFallbackImagePrompts','resolveImagePromptEntries',
  'extractInformationSlideSectionSource','shortenInformationSlideText','buildInformationSlideBrief',
  'getInformationSlideLayoutGuide','resolveImagePresentationMode','buildImagePresentationPromptBlock',
  'normalizeAutoImageReferenceImage','getAutoImageReferenceContext','extractMimeTypeFromDataUrl','buildImageGenerationPrompt'];
const functions = names.map(name => {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(name);
  const tail = source.slice(start + 1).search(/^function /m);
  return source.slice(start, tail < 0 ? source.length : start + 1 + tail);
}).join('\n');
const entries = [
  {slot:'대표 이미지',prompt:'출근길에 얇은 겉옷을 입고 걷는 장면',alt:'출근길 착용',placementHint:'H1 바로 아래',headingHint:''},
  {slot:'본문 이미지 1',prompt:'같은 기준으로 소재를 가까이 비교',alt:'소재 비교',placementHint:'첫 소제목 뒤',headingHint:'1. 소재 비교'},
  {slot:'본문 이미지 2',prompt:'접은 옷을 가방에 넣는 손동작',alt:'휴대 과정',placementHint:'둘째 소제목 뒤',headingHint:'2. 휴대 순서'},
];
const nodes = [
  {tag:'P',text:'출근길 활용 상황을 먼저 살펴봅니다.'},
  {tag:'H2',text:'1. 소재 비교'},
  {tag:'P',text:'1. 소재 비교\n가벼운 원단의 질감을 확인합니다. 가벼운 원단의 질감을 확인합니다. 1.5배라는 수치는 가정입니다.'},
  {tag:'UL',items:['✓ 봉제 부위를 가까이 봅니다.','2) 지퍼 마감을 확인합니다.']},
  {tag:'H3',text:'2. 휴대 순서'},
  {tag:'P',text:'옷을 접어 가방에 넣습니다. 필요한 때 다시 꺼내 입습니다.'},
];
const cases = [
  {name:'standard',presentation:'standard',articleType:'information',formatPreset:'auto',count:2},
  {name:'slide-default',presentation:'info-slide',articleType:'information',formatPreset:'auto',count:3},
  {name:'slide-comparison',presentation:'info-slide',articleType:'comparison',formatPreset:'checklist',count:3},
  {name:'slide-checklist',presentation:'info-slide',articleType:'howto',formatPreset:'auto',count:3},
  {name:'slide-review',presentation:'info-slide',articleType:'review',formatPreset:'auto',count:3},
  {name:'mixed',presentation:'mixed',articleType:'information',formatPreset:'auto',count:3},
  {name:'provided',presentation:'mixed',articleType:'information',formatPreset:'auto',count:'auto',provided:true},
  {name:'rewrite-applied',presentation:'info-slide',articleType:'review',formatPreset:'auto',count:2,provided:true,rewriteRevision:'applied-r1'},
  {name:'reference',presentation:'standard',articleType:'information',formatPreset:'auto',count:1,reference:true},
  {name:'missing-reference',presentation:'standard',articleType:'information',formatPreset:'auto',count:1,referencePrompt:'따뜻한 빛을 참고'},
  {name:'numbered-upper-bound',presentation:'standard',articleType:'information',formatPreset:'auto',count:5,nodes:[{tag:'H2',text:'4. 선택 기준'},{tag:'P',text:'봉제 상태와 휴대성을 확인합니다.'}]},
  {name:'unicode-boundary',presentation:'info-slide',articleType:'information',formatPreset:'auto',count:1,title:'가'.repeat(33)+'😀',summary:'동일한 내용을 확인합니다. 동일한 내용을 확인합니다. e\u0301 결합 문자를 그대로 유지합니다. '+ '나'.repeat(800)},
];
const result = [];
for (const input of cases) {
  const graph = (input.provided ? [] : input.nodes || nodes).map(n => ({tagName:n.tag,textContent:n.text || n.items.join(' '),querySelectorAll:()=>n.items?.map(text=>({textContent:text})) || []}));
  graph.forEach((n,i)=>n.nextElementSibling=graph[i+1] || null);
  const ctx = vm.createContext({state:{length:'medium',autoImageCount:'auto',topic:'',articleType:input.articleType,formatPreset:input.formatPreset},
    window:{ddalkkakLanguage:()=> 'ko'},
    document:{createElement:()=>({content:{querySelectorAll:()=>graph.filter(n=>['H2','H3'].includes(n.tagName))}})},
    normalizeDraft:x=>x,sanitizeDraftHtml:x=>x,getImageAiLabel:()=> '현재 이미지 도구',useEnglishPrompts:()=>false});
  for (const file of ['provided-article.js','english-prompts.js']) vm.runInContext(fs.readFileSync(path.join(root,'extension-local',file),'utf8'),ctx);
  vm.runInContext(functions,ctx);
  const body='첫 문단에서 착용 상황을 설명합니다.\n\n둘째 문단에서 소재를 확인합니다.\n\n셋째 문단에서 옷을 접습니다.\n\n마지막 문단에서 주의점을 정리합니다.';
  const draft=input.provided ? ctx.ProvidedArticle.create('입력 원고',body) : {title:input.title || '출근길 겉옷 선택',summary:input.summary || '소재와 휴대성을 확인합니다.',tags:['겉옷'],html:'fixture HTML nodes',text:body,imagePrompts:entries};
  if(input.rewriteRevision) draft.rewriteRevision=input.rewriteRevision;
  const selected=ctx.resolveImagePromptEntries(draft,input.count);
  const options={imageStyle:input.presentation,additionalRequirements:'차분한 자연광을 사용하세요.',referencePrompt:input.referencePrompt || (input.reference?'색감과 질감을 참고':''),referenceImage:input.reference?{dataUrl:'data:image/png;base64,fixture',name:'reference.png'}:null};
  result.push({input:{...input,nodes:input.nodes || nodes,draft},expected:{analysis:ctx.analyzeAutoImageUpperBound(draft),count:ctx.resolveRequestedAutoImageCount(input.count,draft),fallback:ctx.deriveFallbackImagePrompts(draft,input.count==='auto'?3:input.count),selected,
    briefs:selected.map(e=>ctx.buildInformationSlideBrief(e,draft)),modes:selected.map(e=>ctx.resolveImagePresentationMode(input.presentation,e)),layout:ctx.getInformationSlideLayoutGuide(),ko_prompts:selected.map(e=>ctx.buildImageGenerationPrompt(e,draft,options)),
    english_prompt:ctx.englishImagePrompt({scene:selected[0],draft,style:input.presentation,requirements:options.additionalRequirements,referenceInstructions:options.referencePrompt,format:'Blog illustration or informational slide according to selected style; keep text minimal for standard images. For informational slides, select a concise English heading and key points grounded in the supplied article.'})}});
}
const files=['sidepanel.js','provided-article.js','english-prompts.js'];
process.stdout.write(JSON.stringify({source_commit:'ab4c700',source_release:'1.12.35 / 20261003-r47',source_files:Object.fromEntries(files.map(f=>[f,crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'extension-local',f))).digest('hex')])),adapter_note:'normalizeDraft is an identity fixture boundary; document supplies already-sanitized fixture nodes. Original selection, section walk, brief and prompt functions execute unchanged.',cases:result},null,2)+'\n');
