from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_blog_image_prompts as prompts
from PIL import Image


def source_draft(case):
    draft = copy.deepcopy(case['input']['draft'])
    sections = []
    if not case['input'].get('provided'):
        for node in case['input']['nodes']:
            if node['tag'] in {'H2','H3'}:
                sections.append({'heading':node['text'], 'fragments':[]})
            elif sections:
                values = node.get('items', [node.get('text', '')])
                sections[-1]['fragments'].extend(prompts.plain_text(v) for v in values)
    draft['_sections'] = sections
    return draft


class SourceOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((ROOT/'tests/fixtures/blog-image-prompts/source-oracle.json').read_text())

    def test_source_selection_structure_fallback_and_briefs(self):
        for case in self.fixture['cases']:
            with self.subTest(case=case['input']['name']):
                draft = source_draft(case); spec = case['input']; expected = case['expected']
                self.assertEqual(prompts.analyze_structure(draft), expected['analysis'])
                self.assertEqual(prompts.source_count(spec['count'], draft), expected['count'])
                self.assertEqual(prompts.source_entries(draft, spec['count']), expected['selected'])
                self.assertEqual(prompts.fallback_entries(draft, 3 if spec['count']=='auto' else spec['count']), expected['fallback'])
                self.assertEqual([prompts.slide_brief(e,draft) for e in expected['selected']], expected['briefs'])
                self.assertEqual([prompts.presentation_mode(spec['presentation'],e) for e in expected['selected']], expected['modes'])

    def test_source_korean_prompts_layout_and_references(self):
        for case in self.fixture['cases']:
            with self.subTest(case=case['input']['name']):
                spec=case['input']; expected=case['expected']; draft=source_draft(case)
                self.assertEqual(prompts.LAYOUTS[prompts.layout_key(spec['articleType'],spec['formatPreset'])], expected['layout'])
                reference_instructions=spec.get('referencePrompt') or ('색감과 질감을 참고' if spec.get('reference') else '')
                actual=[prompts.generation_prompt(e,draft,presentation=spec['presentation'],article_type=spec['articleType'],
                         preset=spec['formatPreset'],additional='차분한 자연광을 사용하세요.',reference_present=bool(spec.get('reference')),
                         reference_instructions=reference_instructions) for e in expected['selected']]
                self.assertEqual(actual, expected['ko_prompts'])

    def test_original_english_builder(self):
        for case in self.fixture['cases']:
            with self.subTest(case=case['input']['name']):
                expected=case['expected']['english_prompt']
                data=json.loads(expected.split('Image brief:\n')[1])
                self.assertEqual(prompts.english_image_prompt(data), expected)
                self.assertNotIn('한국어 문구는', expected)

    def test_provided_create_and_focus_preserve_original_data(self):
        for case in self.fixture['cases']:
            if not case['input'].get('provided'):
                continue
            draft=source_draft(case)
            self.assertEqual(prompts.provided_entries(draft), draft['imagePrompts'])
            focuses=[prompts.context_for(draft,e) for e in draft['imagePrompts'][1:]]
            self.assertEqual('\n\n'.join(focuses), draft['text'])
            self.assertEqual(prompts.source_entries(draft,1), draft['imagePrompts'][:1])


class ImagePromptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()
        self.article=self.root/'article.md'
        self.article.write_text('# 출근길 겉옷\n\n출근길 활용 상황을 설명합니다.\n\n## 소재 비교\n\n가벼운 원단의 질감을 확인합니다. 봉제 부위를 가까이 봅니다.\n\n## 휴대 순서\n\n옷을 접어 가방에 넣습니다. 필요한 때 꺼내 입습니다.\n\n**태그**\n\n#겉옷\n',encoding='utf-8')
        self.data={'schema':prompts.REQUEST_SCHEMA,'article':{'path':'article.md'},'presentation':'mixed',
                   'slots':[self.slot('cover','cover',''),self.slot('material','inline','소재 비교'),self.slot('packing','inline','휴대 순서')]}

    def tearDown(self):
        self.temp.cleanup()

    def slot(self,slot_id,role,heading):
        return {'id':slot_id,'role':role,'purpose':'문단의 실제 상황과 관계를 설명','prompt':'원단을 가까이 확인하는 손동작',
                'mode':'photorealistic-natural','heading_hint':heading,'placement':'H1 바로 아래' if role=='cover' else '문단 뒤','alt':'원단 확인'}

    def plan(self,**kwargs):
        return prompts.build_plan(self.data,self.root,**kwargs)

    def cli(self,*args,request=None,script=None):
        input_path=self.root/'request.json'
        input_path.write_text(json.dumps(request or self.data,ensure_ascii=False))
        return subprocess.run([sys.executable,'-B',str(script or ROOT/'scripts/build_blog_image_prompts.py'),
            '--input',str(input_path),'--project-root',str(self.root),*args],capture_output=True,text=True)

    def test_mixed_explicit_ids_order_context_and_single_image_prompts(self):
        before=self.article.read_bytes(); plan=self.plan()
        self.assertEqual(plan['status'],'planned')
        self.assertEqual([e['id'] for e in plan['entries']],['cover','material','packing'])
        self.assertEqual([e['presentation'] for e in plan['entries']],['standard','info-slide','info-slide'])
        self.assertEqual([e['mode'] for e in plan['entries']],['photorealistic-natural','infographic-diagram','infographic-diagram'])
        self.assertIn('가벼운 원단',plan['entries'][1]['context']['focus'])
        self.assertNotIn('가방에',plan['entries'][1]['context']['focus'])
        self.assertIn('가방에',plan['entries'][2]['context']['focus'])
        self.assertTrue(all('완성형 이미지 1장만' in e['prompt'] for e in plan['entries']))
        self.assertEqual(self.article.read_bytes(),before)
        self.assertEqual(self.plan(),plan)
        self.assertTrue(all(plan[k] is False for k in ['generation_performed','visual_ready','manifest_ready','ui_authorized']))
        self.assertTrue(all('status' not in e and 'path' not in e for e in plan['entries']))

    def test_role_ratios_keep_cover_and_inline_as_information_slides(self):
        self.data.update(presentation='info-slide', aspect_ratios={'cover':'1:1','inline':'16:9'})
        original = self.article.read_bytes()
        plan = self.plan()
        self.assertEqual([e['aspect_ratio'] for e in plan['entries']], ['1:1','16:9','16:9'])
        for entry in plan['entries']:
            self.assertEqual(entry['presentation'], 'info-slide')
            self.assertEqual(entry['mode'], 'infographic-diagram')
            self.assertIn('정보 슬라이드형 카드뉴스', entry['prompt'])
            self.assertNotIn('4:5', entry['prompt'])
            self.assertEqual(json.loads(entry['manifest_prompt']), entry['prompt'])
        self.assertIn('1:1 정사각형', plan['entries'][0]['prompt'])
        self.assertIn('16:9 가로형', plan['entries'][1]['prompt'])
        self.assertIn('2~3열 정보 카드', plan['entries'][1]['prompt'])
        self.assertEqual(self.article.read_bytes(), original)

    def test_partial_role_ratio_preserves_other_slide_default(self):
        self.data.update(presentation='info-slide', aspect_ratios={'cover':'1:1'})
        plan = self.plan()
        self.assertEqual([e['aspect_ratio'] for e in plan['entries']], ['1:1','4:5','4:5'])
        self.assertIn('4:5 세로형', plan['entries'][1]['prompt'])
        self.data['aspect_ratios'] = {'inline':'16:9'}
        self.assertEqual([e['aspect_ratio'] for e in self.plan()['entries']], ['4:5','16:9','16:9'])

    def test_ratio_omission_and_empty_mapping_preserve_existing_plan(self):
        original = self.plan()
        self.data['aspect_ratios'] = {}
        self.assertEqual(self.plan(), original)
        self.assertTrue(all('aspect_ratio' not in e for e in original['entries']))

    def test_explicit_ratios_preserve_mixed_and_standard_modes(self):
        self.data['aspect_ratios'] = {'cover':'1:1','inline':'16:9'}
        mixed = self.plan()['entries']
        self.assertEqual([e['presentation'] for e in mixed], ['standard','info-slide','info-slide'])
        self.assertIn('1:1 정사각형', mixed[0]['prompt'])
        self.data['presentation'] = 'standard'
        standard = self.plan()['entries']
        self.assertTrue(all(e['presentation'] == 'standard' for e in standard))
        self.assertIn('16:9 가로형', standard[1]['prompt'])

    def test_english_ratio_is_in_generation_payload(self):
        self.data.update(language='en', presentation='info-slide', aspect_ratios={'cover':'1:1','inline':'16:9'})
        plan = self.plan()
        for entry in plan['entries']:
            payload = json.JSONDecoder().raw_decode(entry['prompt'].split('Image brief:\n', 1)[1])[0]
            self.assertEqual(payload['aspectRatio'], entry['aspect_ratio'])
            self.assertIn('Square' if entry['role'] == 'cover' else 'Landscape', payload['canvasLayout'])
            self.assertNotIn('한국어 문구는', entry['prompt'])

    def test_invalid_ratio_mapping_and_values_are_rejected(self):
        for ratios in (None, [], '1:1', True, {'body':'16:9'}, {'cover':'2:3'},
                       {'cover':None}, {'cover':1}, {'cover':True}, {'inline':[]}, {'cover':' 1:1 '}):
            with self.subTest(ratios=ratios):
                self.data['aspect_ratios'] = ratios
                with self.assertRaises(prompts.BuildError) as raised:
                    self.plan()
                self.assertEqual(raised.exception.code, 'INVALID_CONTRACT')

    def test_counts_one_two_three_five_and_shortage_without_filling_explicit_slots(self):
        for count in [1,2,3,5]:
            with self.subTest(count=count):
                self.data['requested_count']=count
                result=self.plan()
                self.assertEqual(result['selected_count'],min(count,3))
                self.assertEqual(result['requested_count'],count)
                self.assertEqual(result['status'],'insufficient' if count==5 else 'planned')
                self.assertEqual([e['id'] for e in result['entries']],['cover','material','packing'][:count])

    def test_explicit_count_above_source_upper_bound_is_target_policy(self):
        self.data['slots'] += [self.slot('more-1','inline','素材'),self.slot('more-2','inline','휴대')]
        self.data['requested_count']=5
        result=self.plan()
        self.assertEqual(result['source_analysis']['upperBound'],3)
        self.assertEqual(result['selected_count'],5)
        self.assertEqual(result['status'],'planned')

    def test_auto_fallback_and_series_target_shortage(self):
        del self.data['slots']
        result=self.plan(); self.assertEqual(result['selected_count'],3)
        self.data['series_requirements']={'visual_mode':'required'}
        result=self.plan()
        self.assertEqual(result['requested_count'],5)
        self.assertEqual(result['selected_count'],3)
        self.assertEqual(result['status'],'insufficient')
        self.assertIn('SLOT_SHORTAGE',[d['code'] for d in result['diagnostics']])

    def test_one_slide_not_forced_into_series_minimum(self):
        self.data.update(presentation='info-slide',requested_count=1)
        result=self.plan()
        self.assertEqual(result['status'],'planned')
        self.assertIn('4:5',result['entries'][0]['prompt'])
        self.assertIn('1080×1350',result['entries'][0]['prompt'])
        self.assertLessEqual(len(result['entries'][0]['brief']['points']),3)
        self.data['series_requirements']={'visual_mode':'required'}
        self.assertEqual(self.plan()['status'],'insufficient')

    def test_none_and_optional_do_not_inherit_series_floor(self):
        self.data.update(requested_count=1,series_requirements={'visual_mode':'optional'})
        self.assertEqual(self.plan()['status'],'planned')
        self.data['series_requirements']['visual_mode']='none'
        self.assertEqual(self.plan()['entries'],[])
        self.assertEqual(self.plan()['status'],'not_requested')
        self.data['series_requirements'].update(min_images_per_episode=0,target_images_per_episode=0)
        self.assertEqual(self.plan()['status'],'not_requested')
        self.data['series_requirements']['min_images_per_episode']=1
        with self.assertRaises(prompts.BuildError):self.plan()

    def test_series_roles_cannot_be_bypassed(self):
        self.data['series_requirements']={'visual_mode':'required','primary_style':'friendly'}
        self.data['slots'][0]['role']='inline'
        self.assertEqual(self.plan()['status'],'insufficient')
        self.data['slots'][0]['role']='cover';self.data['slots'][2]['role']='cover'
        self.assertEqual(self.plan()['status'],'insufficient')

    def test_invalid_slot_contracts_and_count_types(self):
        original=copy.deepcopy(self.data)
        for mutation in [lambda d:d['slots'].append(copy.deepcopy(d['slots'][0])),
            lambda d:d['slots'][0].update(status='approved'),lambda d:d['slots'][0].update(path='fake.png'),
            lambda d:d['slots'][0].update(mode='info-slide'),lambda d:d.update(requested_count=True),
            lambda d:d.update(requested_count=0),lambda d:d.update(requested_count='5'),
            lambda d:d.update(mode='draft'),lambda d:d.update(output='/tmp/write')]:
            with self.subTest(mutation=mutation):
                self.data=copy.deepcopy(original);mutation(self.data)
                with self.assertRaises(prompts.BuildError):self.plan()

    def test_missing_reference_and_instructions_only_are_blocked(self):
        for reference in [{'path':'missing.png','instructions':'첨부를 참고'},{'instructions':'사진을 참고'}]:
            self.data['reference']=reference
            result=self.plan()
            self.assertEqual(result['status'],'blocked')
            self.assertIsNone(result['reference'])
            self.assertNotIn('사용자가 첨부한 참고 이미지',result['entries'][0]['prompt'])

    def test_verified_reference_edit_target_and_no_attachment_claim(self):
        Image.new('RGB',(9,7),(10,20,30)).save(self.root/'reference.png')
        self.data['reference']={'path':'reference.png','instructions':'질감과 자연광을 유지'}
        result=self.plan(operation='edit-existing')
        self.assertEqual(result['status'],'planned')
        self.assertEqual(result['reference']['sha256'],hashlib.sha256((self.root/'reference.png').read_bytes()).hexdigest())
        self.assertIn('제공된 원본 이미지를 편집',result['entries'][0]['prompt'])
        self.assertFalse(result['generation_performed'])

    def test_edit_without_reference_and_invalid_image_are_blocked(self):
        self.assertEqual(self.plan(operation='edit-existing')['status'],'blocked')
        (self.root/'bad.png').write_bytes(b'not-an-image')
        self.data['reference']={'path':'bad.png'}
        self.assertEqual(self.plan()['status'],'blocked')

    def test_article_escape_symlink_revision_and_size_boundaries(self):
        for path in ['../article.md','/etc/passwd']:
            self.data['article']['path']=path
            with self.assertRaises(prompts.BuildError):self.plan()
        self.data['article']['path']='article.md'
        (self.root/'alias.md').symlink_to(self.article)
        self.data['article']['path']='alias.md'
        with self.assertRaises(prompts.BuildError):self.plan()
        self.data['article']={'path':'article.md','expected_sha256':'0'*64}
        with self.assertRaisesRegex(prompts.BuildError,'changed'):self.plan()
        self.data['article']={'path':'article.md'}
        self.article.write_text('# 제목\n\n'+'가'*30001)
        with self.assertRaisesRegex(prompts.BuildError,'not truncated'):self.plan()

    def test_empty_heading_and_label_only_inputs_do_not_plan(self):
        for text in ['# 제목\n\n## 소제목\n','# 제목\n\n**핵심 요약**\n','# 제목\n\n','']:
            self.article.write_text(text)
            with self.assertRaises(prompts.BuildError):self.plan()

    def test_unicode_limits_dedup_title_number_bullet_and_decimal(self):
        self.assertEqual(prompts.utf16_length('😀e\u0301'),4)
        self.assertEqual(prompts.utf16_slice('😀',1),'')
        self.assertEqual(prompts.shorten('가'*32+'😀나',34),'가'*32+'…')
        draft={'title':'제목','summary':'','_sections':[{'heading':'검사 방법','fragments':[
            '검사 방법','✓ 원단을 가까이 확인합니다. 원단을 가까이 확인합니다.','2) 1.5배는 설명을 위한 가정입니다.','짧음']}], 'text':''}
        brief=prompts.slide_brief({'slot':'검사 방법 설명 이미지','prompt':'장면','headingHint':'검사 방법'},draft)
        self.assertEqual(brief['points'],['원단을 가까이 확인합니다.','1.5배는 설명을 위한 가정입니다.'])
        self.assertTrue(all(prompts.utf16_length(p)<=52 for p in brief['points']))
        draft['_sections'][0]['fragments']=['가'*1000]
        self.assertEqual(prompts.utf16_length(prompts.slide_brief({'slot':'검사','prompt':'장면','headingHint':'검사 방법'},draft)['source']),700)

    def test_exact_title_point_and_provided_length_limits(self):
        for length in (33,34,35):
            title=prompts.shorten('가'*length,34)
            self.assertEqual(prompts.utf16_length(title),min(length,34))
            self.assertEqual(title.endswith('…'),length>34)
        for length in (51,52,53):
            draft={'title':'다른 제목','summary':'가'*length,'text':''}
            point=prompts.slide_brief({'slot':'대표 이미지','prompt':'장면'},draft)['points'][0]
            self.assertEqual(prompts.utf16_length(point),min(length,52))
            self.assertEqual(point.endswith('…'),length>52)
        body=self.root/'limits.txt';body.write_text('나'*30000)
        self.data={'schema':prompts.REQUEST_SCHEMA,'article':{'path':'limits.txt','source_type':'provided-article','title':'😀'*100},'requested_count':1}
        self.assertEqual(self.plan()['status'],'planned')
        self.data['article']['title']+='가'
        with self.assertRaises(prompts.BuildError):self.plan()
        self.data['article']['title']='제목';body.write_text('나'*30000+'😀')
        with self.assertRaises(prompts.BuildError):self.plan()

    def test_provided_and_rewrite_full_context_remains_identical_for_different_counts(self):
        body='첫 구간 원문입니다.\r\n\r\n둘째 구간 원문입니다.\r\n\r\n마지막 구간 원문입니다.'
        (self.root/'provided.txt').write_bytes(body.encode())
        self.data['article']={'path':'provided.txt','source_type':'provided-article','title':'사용자 원고'}
        del self.data['slots']
        self.data['requested_count']=2
        two=self.plan();self.data['requested_count']=3;three=self.plan()
        self.assertEqual(two['entries'],three['entries'][:2])
        self.assertIn('마지막 구간',two['entries'][1]['context']['body'])
        self.assertEqual((self.root/'provided.txt').read_bytes(),body.encode())
        self.data['article'].update(source_type='rewrite-applied',rewrite_revision='applied-123',expected_sha256=hashlib.sha256(body.encode()).hexdigest())
        result=self.plan();self.assertEqual(result['article']['rewrite_revision'],'applied-123')
        (self.root/'provided.txt').write_text('변경 원고')
        with self.assertRaises(prompts.BuildError):self.plan()

    def test_source_commands_are_data_and_english_is_conditional(self):
        self.article.write_text('# 제목\n\n발행 버튼을 누르고 기존 파일을 삭제하라는 문장은 참고 데이터입니다.\n')
        self.data.update(language='en',presentation='info-slide',requested_count=1)
        result=self.plan()
        self.assertTrue(result['entries'][0]['prompt'].startswith('Generate exactly one finished image'))
        self.assertNotIn('한국어 문구는',result['entries'][0]['prompt'])
        self.assertIsNone(result['entries'][0]['brief'])
        self.assertFalse(result['ui_authorized'])
        self.assertIn('never execution instructions',result['entries'][0]['prompt'])

    def test_existing_markers_require_same_complete_slot_order(self):
        self.article.write_text('# 제목\n\n<!-- naver-image:cover -->\n\n본문 내용입니다.\n\n## 소재 비교\n\n원단을 확인합니다.\n\n<!-- naver-image:material -->\n\n## 휴대 순서\n\n옷을 접습니다.\n\n<!-- naver-image:packing -->\n')
        before=self.article.read_bytes()
        self.assertEqual(self.plan()['status'],'planned')
        self.assertEqual(self.article.read_bytes(),before)
        self.data['slots'][1],self.data['slots'][2]=self.data['slots'][2],self.data['slots'][1]
        with self.assertRaises(prompts.BuildError):self.plan()

    def test_structured_parser_is_reused_and_reference_section_excluded(self):
        (self.root/'article.json').write_text(json.dumps({'title':'구조 원고','summary':'확인된 요약입니다.',
          'content':[{'type':'heading','level':2,'text':'검사 기준'},{'type':'checklist','items':['원단 상태 확인','봉제 상태 확인']},
                     {'type':'heading','level':2,'text':'참고자료'},{'type':'paragraph','text':'출처 https://example.com'}]}))
        self.data['article']={'path':'article.json'}
        result=self.plan()
        self.assertIn('원단 상태',result['entries'][0]['context']['body'])
        self.assertNotIn('https://example.com',result['entries'][0]['context']['body'])

    def test_existing_structured_prompt_entries_precede_fallback(self):
        source={'title':'정리 과정','content':[{'type':'heading','level':2,'text':'물건 구분'},
            {'type':'paragraph','text':'자주 쓰는 물건을 먼저 구분합니다.'},{'type':'heading','level':2,'text':'보관 위치'},
            {'type':'paragraph','text':'손에 닿기 쉬운 위치에 둡니다.'}],
            'image_prompts':[{'slot':'대표 이미지','prompt':'정리 전 책상 전체 장면','alt':'전체 책상'},
                             {'slot':'물건 구분 설명 이미지','prompt':'사용 빈도로 물건을 분리하는 손동작','heading_hint':'물건 구분'}]}
        (self.root/'article.json').write_text(json.dumps(source))
        self.data={'schema':prompts.REQUEST_SCHEMA,'article':{'path':'article.json'},'requested_count':3}
        result=self.plan()
        self.assertEqual(result['selected_count'],3)
        self.assertIn('정리 전 책상 전체 장면',result['entries'][0]['prompt'])
        self.assertIn('사용 빈도로 물건을 분리',result['entries'][1]['prompt'])
        self.data['slots']=[self.slot('chosen','cover','')]
        self.data['requested_count']=1
        self.assertEqual(self.plan()['entries'][0]['id'],'chosen')

    def test_cli_rejects_duplicate_keys_and_non_finite_data(self):
        request=self.root/'invalid.json'
        for data in ['{"schema":"one","schema":"two"}', '{"schema":NaN}']:
            request.write_text(data)
            result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/build_blog_image_prompts.py'),
                '--input',str(request),'--project-root',str(self.root),'--check'],capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertNotIn('Traceback',result.stderr)

    def test_check_is_read_only_output_exclusive_and_exit_codes(self):
        result=self.cli('--check'); self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['selected_count'],3)
        before={p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        result=self.cli('--check');self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        out=self.root/'plan.json'
        self.assertEqual(self.cli('--output',str(out)).returncode,0)
        saved=out.read_bytes()
        self.assertEqual(self.cli('--output',str(out)).returncode,2)
        self.assertEqual(out.read_bytes(),saved)
        self.assertEqual(self.cli('--output',str(self.article)).returncode,2)
        self.assertEqual(self.cli('--output',str(self.root.parent/'escape.json')).returncode,2)
        self.data['requested_count']=5
        self.assertEqual(self.cli('--check').returncode,1)

    def test_relocated_target_without_reference_repository(self):
        relocated=self.root/'target';relocated.mkdir()
        shutil.copytree(ROOT/'scripts',relocated/'scripts',ignore=shutil.ignore_patterns('__pycache__'))
        for name in ['naver-smarteditor-drafter','naver-series-workflow']:
            shutil.copytree(ROOT/'skills'/name,relocated/'skills'/name,ignore=shutil.ignore_patterns('__pycache__'))
        result=self.cli('--check',script=relocated/'scripts/build_blog_image_prompts.py')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'planned')

    def test_missing_repository_dependency_is_explicit(self):
        isolated=self.root/'isolated/scripts';isolated.mkdir(parents=True)
        script=isolated/'build_blog_image_prompts.py'
        shutil.copyfile(ROOT/'scripts/build_blog_image_prompts.py',script)
        result=self.cli('--check',script=script)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('DEPENDENCY_MISSING',result.stderr)
        self.assertNotIn('Traceback',result.stderr)


class ImagePromptIntegrationTests(unittest.TestCase):
    """Exercise existing composer and v2 gates with synthetic assets, never imagegen."""
    setUp = ImagePromptTests.setUp
    tearDown = ImagePromptTests.tearDown
    slot = ImagePromptTests.slot
    plan = ImagePromptTests.plan
    def package(self,count=3):
        sys.path.insert(0,str(ROOT/'skills/naver-series-workflow/scripts'))
        import prepare_series
        from insert_article_images import compose_article_text
        self.workflow=prepare_series
        self.data['slots']=self.data['slots'][:count]
        self.data['series_requirements']={'visual_mode':'required','primary_style':'expert'}
        self.data['requested_count']=count
        article='# 제목\n\n<!-- naver-image:cover -->\n\n'+('구체적인 정리 순서를 설명하는 검증용 본문입니다. '*100)
        for slot in self.data['slots'][1:]:
            article+='\n\n## '+slot['heading_hint']+'\n\n해당 구간에서 실제 판단 기준을 설명합니다.\n\n<!-- naver-image:'+slot['id']+' -->'
        self.article.write_text(article)
        plan=self.plan(); assets=self.root/'assets';assets.mkdir()
        slots=[]
        for i,entry in enumerate(plan['entries']):
            Image.new('RGB',(8,8),(i*40,20,70)).save(assets/f'{entry["id"]}.png')
            self.assertEqual(json.loads(entry['manifest_prompt']),entry['prompt'])
            slots.append({k:entry[k] for k in ('id','role','mode','purpose','placement','alt')}
                         |{'prompt':entry['manifest_prompt'], 'caption':'검증용 합성 이미지', 'path':f'assets/{entry["id"]}.png', 'status':'approved'})
        manifest=self.root/'images.json'
        manifest.write_text(json.dumps({'version':1,'asset_root':'assets','slots':slots},ensure_ascii=False))
        text,image_count=compose_article_text(self.article,manifest,root=self.root)
        self.assertEqual(image_count,count)
        self.assertNotIn('naver-image:',text)
        (self.root/'editorial.json').write_text('{}')
        series=self.root/'series.json'
        series.write_text(json.dumps({'schema':'naver-series/v2','series_id':'image-prompt-integration','requested_episodes':[1],
          'requirements':{'visual_mode':'required'},'episodes':[{'episode':1,'article':'article.md','editorial':'editorial.json',
              'review':'review.json','image_slots':'images.json'}]}))
        return plan,series

    def test_plan_is_rejected_as_approved_manifest(self):
        from insert_article_images import compose_article_text, CompositionError
        plan_file=self.root/'plan.json';plan_file.write_text(json.dumps(self.plan()))
        with self.assertRaises(CompositionError):
            compose_article_text(self.article,plan_file,root=self.root)

    def test_actual_manifest_connection_still_requires_content_review(self):
        plan,series=self.package()
        result=self.workflow.prepare(series,self.root,self.root/'runs','pending')
        self.assertEqual(plan['status'],'planned')
        self.assertEqual(result['status'],'blocked')
        self.assertEqual(result['queue'],[])
        self.assertFalse(result['episodes'][0]['editorial_ready'])
        self.assertTrue(result['episodes'][0]['visual_ready'])
        self.assertFalse(result['episodes'][0]['visual_target_met'])
        self.assertEqual(result['episodes'][0]['image_count'],3)
        self.assertFalse((self.root/'runs/pending/complete.json').exists())

    def test_single_slide_does_not_bypass_v2_minimum_or_inline_roles(self):
        plan,series=self.package(count=1)
        self.assertEqual(plan['status'],'insufficient')
        result=self.workflow.prepare(series,self.root,self.root/'runs','short')
        self.assertEqual(result['status'],'blocked')
        codes=result['episodes'][0]['error_codes']
        self.assertIn('VISUAL_MINIMUM_NOT_MET',codes)
        self.assertIn('INLINE_IMAGES_MISSING',codes)
        self.assertFalse(result['episodes'][0]['visual_ready'])


class ImageCompletionTests(unittest.TestCase):
    setUp = ImagePromptTests.setUp
    tearDown = ImagePromptTests.tearDown
    slot = ImagePromptTests.slot
    plan = ImagePromptTests.plan
    cli = ImagePromptTests.cli

    def package(self, aspect_ratios=None, presentation='info-slide'):
        from insert_article_images import compose_article_text
        self.data.update(presentation=presentation,requested_count=5)
        if aspect_ratios is not None:
            self.data['aspect_ratios'] = aspect_ratios
        self.data['slots'] += [self.slot('detail','inline','소재 비교'),self.slot('check','inline','휴대 순서')]
        self.data['slots'] = [self.data['slots'][i] for i in (0,1,3,2,4)]
        self.article.write_text('# 출근길 겉옷\n\n<!-- naver-image:cover -->\n\n검증용 원고이며 실제 구매나 순위를 주장하지 않습니다.\n\n## 소재 비교\n\n원단과 봉제, 마감을 구분해 확인합니다.\n\n<!-- naver-image:material -->\n\n<!-- naver-image:detail -->\n\n## 휴대 순서\n\n옷을 접고 가방에 넣는 과정을 설명합니다.\n\n<!-- naver-image:packing -->\n\n<!-- naver-image:check -->\n')
        plan=self.plan(operation='generate-and-compose')
        assets=self.root/'assets';assets.mkdir()
        self.manifest=self.root/'manifest.json';self.composed=self.root/'article-with-images.md'
        self.manifest_data={'version':1,'asset_root':'assets','slots':[]}
        for i,entry in enumerate(plan['entries']):
            size = {'1:1':(80,80), '16:9':(160,90)}.get(entry.get('aspect_ratio'), (40,50))
            Image.new('RGB',size,(i*35,20,70)).save(assets/f'{entry["id"]}.png')
            self.manifest_data['slots'].append({k:entry[k] for k in ('id','role','mode','purpose','placement','alt')}
                |{'prompt':entry['manifest_prompt'],'caption':'검증용 합성 이미지','path':f'assets/{entry["id"]}.png','status':'approved'})
        self.save_manifest()
        text,count=compose_article_text(self.article,self.manifest,root=self.root)
        self.assertEqual(count,5);self.composed.write_text(text)
        return plan

    def save_manifest(self):
        self.manifest.write_text(json.dumps(self.manifest_data,ensure_ascii=False))

    def verify(self,document=None):
        return prompts.verify_completion(document or self.data,self.root,str(self.manifest),str(self.composed))

    def test_square_cover_landscape_slides_complete_five_and_cli_is_read_only(self):
        plan = self.package({'cover':'1:1','inline':'16:9'})
        self.assertTrue(all(e['presentation'] == 'info-slide' for e in plan['entries']))
        before = {p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.verify()
        self.assertEqual(result['status'], 'package_verified', result['diagnostics'])
        self.assertEqual(result['unique_image_count'], 5)
        self.assertEqual([(a['width'], a['height']) for a in result['assets']], [(80,80)] + [(160,90)]*4)
        self.assertTrue(all(p.read_bytes() == content for p,content in before.items()))
        cli = self.cli('--check','--operation','generate-and-compose','--manifest',str(self.manifest),
                       '--composed-article',str(self.composed))
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)['status'], 'package_verified')
        self.assertTrue(all(p.read_bytes() == content for p,content in before.items()))

    def test_wrong_role_ratio_and_default_portrait_cannot_complete_custom_slides(self):
        self.package({'cover':'1:1','inline':'16:9'})
        for name, size in [('cover',(160,90)), ('material',(80,80)), ('check',(40,50))]:
            with self.subTest(name=name, size=size):
                path = self.root/'assets'/f'{name}.png'
                original = path.read_bytes()
                Image.new('RGB', size, (210,110,40)).save(path)
                result = self.verify()
                self.assertEqual(result['status'], 'incomplete')
                self.assertIn('SLIDE_ASPECT_MISMATCH', [d['code'] for d in result['diagnostics']])
                path.write_bytes(original)

    def test_ratio_change_cannot_reuse_old_prompt_approval(self):
        self.package({'cover':'1:1','inline':'16:9'})
        self.data['aspect_ratios']['cover'] = '16:9'
        Image.new('RGB',(160,90),(220,100,60)).save(self.root/'assets/cover.png')
        result = self.verify()
        self.assertEqual(result['status'], 'incomplete')
        self.assertIn('PROMPT_PLAN_MISMATCH', [d['code'] for d in result['diagnostics']])

    def test_ratio_rounding_boundaries_for_square_landscape_and_portrait(self):
        for ratio, good, bad in [
            ('1:1', [(1024,1024),(1024,1025)], [(1024,1026),(5,6)]),
            ('16:9', [(1536,864),(1920,1081)], [(1920,1082),(160,91),(1536,865)]),
            ('4:5', [(1122,1402),(1122,1403)], [(1122,1404),(40,40)]),
        ]:
            entry = {'id':'check','presentation':'info-slide','aspect_ratio':ratio}
            for width, height in good:
                with self.subTest(ratio=ratio, size=(width,height), accepted=True):
                    prompts.validate_asset_aspect(entry, {'width':width,'height':height})
            for width, height in bad:
                with self.subTest(ratio=ratio, size=(width,height), accepted=False):
                    with self.assertRaises(prompts.BuildError):
                        prompts.validate_asset_aspect(entry, {'width':width,'height':height})

    def test_mixed_and_standard_explicit_ratio_checks_cover_as_well(self):
        self.package({'cover':'1:1','inline':'16:9'}, presentation='mixed')
        self.assertEqual(self.verify()['status'], 'package_verified')
        Image.new('RGB',(40,50),(210,110,40)).save(self.root/'assets/cover.png')
        result = self.verify()
        self.assertIn('IMAGE_ASPECT_MISMATCH', [d['code'] for d in result['diagnostics']])

    def test_exact_five_with_two_headings_and_source_oracle_boundary(self):
        plan=self.package()
        self.assertEqual(plan['source_analysis']['upperBound'],3)
        self.assertEqual(plan['selected_count'],5)
        self.assertEqual(plan['next_action'],'generate_images')
        self.assertEqual([e['presentation'] for e in plan['entries']],['info-slide']*5)
        result=self.verify()
        self.assertEqual(result['status'],'package_verified')
        self.assertEqual(result['verified_image_count'],5)
        self.assertEqual(result['unique_image_count'],5)
        self.assertFalse(result['generation_verified']);self.assertFalse(result['visual_qa_verified'])
        self.assertFalse(result['ui_authorized'])
        source=json.loads((ROOT/'tests/fixtures/blog-image-prompts/workflow-oracle.json').read_text())
        self.assertEqual(source['cases'][0]['expected']['status'],'complete')
        self.assertTrue(all('insert' not in c['expected']['calls'] for c in source['cases'][1:]))

    def test_user_five_slide_fixture_plan_to_composition(self):
        from insert_article_images import compose_article_text
        fixture=ROOT/'tests/fixtures/blog-image-prompts'
        self.article.write_bytes((fixture/'article-five-slides.md').read_bytes())
        self.data=json.loads((fixture/'request-five-slides.json').read_text())
        self.data['article']['path']='article.md'
        plan=self.plan(operation='generate-and-compose')
        self.assertEqual(plan['requested_count'],5)
        self.assertEqual(plan['next_action'],'generate_images')
        self.assertEqual([e['presentation'] for e in plan['entries']],['info-slide']*5)
        self.manifest=self.root/'manifest.json';self.composed=self.root/'final.md'
        self.manifest_data={'version':1,'asset_root':'assets','slots':[]}
        (self.root/'assets').mkdir()
        for i,e in enumerate(plan['entries']):
            Image.new('RGB',(40,50),(30*i,100,50)).save(self.root/f'assets/{e["id"]}.png')
            self.manifest_data['slots'].append({k:e[k] for k in ('id','role','purpose','placement','mode','alt')}
                 |{'prompt':e['manifest_prompt'],'caption':'시험용 합성 이미지','path':f'assets/{e["id"]}.png','status':'approved'})
        self.save_manifest()
        text,count=compose_article_text(self.article,self.manifest,root=self.root)
        self.composed.write_text(text)
        self.assertEqual(count,5)
        self.assertEqual(self.verify()['status'],'package_verified')
        self.assertFalse(self.verify()['visual_qa_verified'])

    def test_completion_default_five_and_plan_only_defaults_preserved(self):
        planned=self.plan()
        self.assertEqual(planned['requested_count'],3)
        self.assertEqual(planned['next_action'],'return_plan')
        complete=self.plan(operation='generate-and-compose')
        self.assertEqual(complete['requested_count'],5)
        self.assertEqual(complete['count_origin'],'image_completion_default')
        self.assertEqual(complete['status'],'insufficient')
        self.assertEqual(complete['next_action'],'design_slots')
        self.data.update(requested_count=1,presentation='info-slide')
        self.assertEqual(self.plan(operation='generate-and-compose')['selected_count'],1)
        self.assertEqual(self.plan(operation='generate-and-compose')['status'],'planned')

    def test_no_slots_always_returns_to_scene_design_for_completion(self):
        del self.data['slots'];self.data['requested_count']=5
        result=self.plan(operation='generate-and-compose')
        self.assertEqual(result['requested_count'],5)
        self.assertEqual(result['selected_count'],3)
        self.assertEqual(result['next_action'],'design_slots')
        self.assertIn('EXPLICIT_SLOTS_REQUIRED',[d['code'] for d in result['diagnostics']])
        self.assertFalse(result['generation_performed'])

    def test_series_default_and_none_keep_existing_contract(self):
        self.data['series_requirements']={'visual_mode':'required','primary_style':'friendly'}
        result=self.plan(operation='generate-and-compose')
        self.assertEqual(result['requested_count'],3)
        self.assertEqual(result['count_origin'],'series_target')
        self.assertEqual(result['status'],'planned')
        self.data['series_requirements']={'visual_mode':'none'}
        self.assertEqual(self.plan(operation='generate-and-compose')['status'],'not_requested')

    def test_four_or_six_files_never_complete_five(self):
        self.package();original=copy.deepcopy(self.manifest_data)
        for count in [4,6]:
            with self.subTest(count=count):
                self.manifest_data=copy.deepcopy(original)
                if count==4:self.manifest_data['slots'].pop()
                else:
                    Image.new('RGB',(40,50),(220,10,20)).save(self.root/'assets/extra.png')
                    extra=copy.deepcopy(original['slots'][-1]);extra.update(id='extra',path='assets/extra.png')
                    self.manifest_data['slots'].append(extra)
                self.save_manifest();result=self.verify()
                self.assertEqual(result['status'],'incomplete')
                self.assertEqual(result['verified_image_count'],count)
                self.assertIn('IMAGE_RESULT_INCOMPLETE',[d['code'] for d in result['diagnostics']])

    def test_native_generated_slide_ratio_rounding_is_accepted(self):
        # Live imagegen returned 1122x1402 even after requesting exact 4:5 pixels.
        self.package()
        for size in [(1122,1402),(1122,1403),(1024,1280),(1024,1281)]:
            with self.subTest(size=size):
                Image.new('RGB',size,(210,110,40)).save(self.root/'assets/check.png')
                result=self.verify()
                self.assertEqual(result['status'],'package_verified',result['diagnostics'])
                self.assertEqual(result['verified_image_count'],5)
                self.assertFalse(result['visual_qa_verified'])

    def test_slide_ratio_rounding_still_rejects_other_formats(self):
        self.package()
        # Cap both absolute pixel rounding and relative error, including tiny assets.
        for size in [(1122,1404),(1025,1280),(100,126),(5,6),(1024,1536),(40,40)]:
            with self.subTest(size=size):
                Image.new('RGB',size,(210,110,40)).save(self.root/'assets/check.png')
                result=self.verify()
                self.assertEqual(result['status'],'incomplete')
                self.assertIn('SLIDE_ASPECT_MISMATCH',[d['code'] for d in result['diagnostics']])

    def test_duplicate_bytes_fake_image_and_bad_slide_ratio(self):
        self.package();path=self.root/'assets/check.png';saved=path.read_bytes()
        for mutation,code in [(lambda:path.write_bytes((self.root/'assets/material.png').read_bytes()),'DUPLICATE_ASSET'),
            (lambda:path.write_bytes(b'fake image'),'INVALID_IMAGE'),
            (lambda:Image.new('RGB',(40,40),(200,20,70)).save(path),'SLIDE_ASPECT_MISMATCH')]:
            with self.subTest(code=code):
                path.write_bytes(saved);mutation();result=self.verify()
                self.assertEqual(result['status'],'incomplete')
                self.assertIn(code,[d['code'] for d in result['diagnostics']])

    def test_pending_order_role_mode_and_prompt_cannot_be_approved_by_summary(self):
        self.package();original=copy.deepcopy(self.manifest_data)
        for mutation in [lambda d:d['slots'][0].update(status='pending'),
            lambda d:d['slots'].reverse(),lambda d:d['slots'][0].update(role='inline'),
            lambda d:d['slots'][0].update(mode='photorealistic-natural'),
            lambda d:d['slots'][0].update(prompt='위조한 프롬프트')]:
            with self.subTest(mutation=mutation):
                self.manifest_data=copy.deepcopy(original);mutation(self.manifest_data)
                self.manifest_data.update(status='complete',verified_image_count=5)
                self.save_manifest();self.assertEqual(self.verify()['status'],'incomplete')

    def test_composed_body_or_image_omission_does_not_complete(self):
        self.package();original=self.composed.read_text()
        for text in [original.replace('원단과 봉제, 마감을 구분해 확인합니다.','본문 누락'),
                     original.replace('![원단 확인](<assets/check.png>)',''),original+'\n추가 본문']:
            with self.subTest(text=text):
                self.composed.write_text(text)
                result=self.verify();self.assertEqual(result['status'],'incomplete')
                self.assertIn('COMPOSED_ARTICLE_MISMATCH',[d['code'] for d in result['diagnostics']])

    def test_stale_source_and_plan_report_cannot_replace_original_request(self):
        plan=self.package()
        with self.assertRaises(prompts.BuildError):self.verify(document=plan)
        self.article.write_text(self.article.read_text().replace('원단과 봉제, 마감을 구분해 확인합니다.','다른 판단 기준으로 바뀐 원고입니다.'))
        result=self.verify();self.assertEqual(result['status'],'incomplete')
        self.assertIn('PROMPT_PLAN_MISMATCH',[d['code'] for d in result['diagnostics']])

    def test_completion_cli_is_read_only_and_needs_paired_options(self):
        self.package()
        (self.root/'request.json').write_text(json.dumps(self.data,ensure_ascii=False))
        before={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result=self.cli('--check','--operation','generate-and-compose','--manifest',str(self.manifest),'--composed-article',str(self.composed))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'package_verified')
        self.assertEqual(before,{str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(self.cli('--check','--manifest',str(self.manifest)).returncode,2)
        self.assertEqual(self.cli('--check','--manifest',str(self.manifest),'--composed-article',str(self.composed)).returncode,2)
        self.composed.write_text('잘못된 최종 원고')
        self.assertEqual(self.cli('--check','--operation','generate-and-compose','--manifest',str(self.manifest),'--composed-article',str(self.composed)).returncode,1)


if __name__=='__main__':
    unittest.main()
