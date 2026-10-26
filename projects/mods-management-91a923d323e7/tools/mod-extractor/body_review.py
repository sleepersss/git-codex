"""Readable local evidence report. Source strings are always escaped."""
from pathlib import Path
from html import escape
import json


def body_report_artifact(run):
    try:return {'body_report':str(write_body_review(run)),'body_report_status':'ready'}
    except (OSError,ValueError,KeyError,TypeError) as error:
        return {'body_report_status':'unavailable','body_report_error':str(error)}


def write_body_review(run):
    run=Path(run)
    def read(name):
        p=run/name
        return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else {}
    decision=read('body-decision.json');candidates=read('body-candidates.json');coverage=read('source-draw-coverage.json')
    e=lambda value:escape(str(value),quote=True)
    statuses={'selected':'已选择一套源状态','ambiguous':'身体版本待选择','unresolved':'来源条件或分组待核对',
        'search_limited':'状态检查达到上限'}
    labels={'clothes':'服装或附件','unknown':'标签无法确认','different_source_state':'属于其他源状态'}
    excluded={r['name']:labels.get(r['reason'],r['reason']) for r in candidates.get('excluded',[])}
    chosen=set(candidates.get('selected',[]))
    parts=''.join('<tr><td>'+e(r['name'])+'</td><td>'+e(r.get('label',''))+'</td><td>'+
        e('本次候选' if r['name'] in chosen else excluded.get(r['name'],'待核对'))+'</td><td>'+
        e('；'.join(r.get('conditions',[])))+'</td></tr>' for r in candidates.get('parts',[]))
    alternatives=''.join('<li><p>部件：'+e('、'.join(r['names']))+'</p><p>来源控制值：'+
        e(json.dumps(r.get('controls',{}),ensure_ascii=False))+'</p></li>' for r in candidates.get('alternatives',[]))
    previews=''.join('<figure><img alt="'+e(title)+'" src="'+folder+'/'+view+'.png"><figcaption>'+e(title)+
        '</figcaption></figure>' for folder in ('body-previews','full-previews') for view,title in
        (('front','正面'),('back','背面'),('side','侧面')) if (run/folder/(view+'.png')).is_file())
    html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>身体提取检查</title>
<style>body{font:16px/1.6 "Microsoft YaHei UI",sans-serif;color:#172033;background:#f6f8fb;margin:0}
main{max-width:1200px;margin:auto;padding:28px}section{background:white;padding:20px;margin:20px 0;border:1px solid #ccd4df;border-radius:8px}
h1{font-size:26px}h2{font-size:20px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #ccd4df;padding:10px;text-align:left;overflow-wrap:anywhere}
.scroll{overflow-x:auto}figure{display:inline-block;margin:8px}img{width:260px;max-width:100%;height:auto}a{color:#1749ae}p{overflow-wrap:anywhere}</style>
<main><h1>身体提取检查</h1>'''
    html+='<section><h2>'+e(statuses.get(candidates.get('status'),'身体检查记录'))+'</h2><p>'+e(decision.get('message','尚未完成检查'))+'</p>'
    html+='<p>已检查状态：'+e(candidates.get('states_evaluated',0))+'。标签与源数据检查不代表已完成外观、解剖或游戏适配验收。</p>'
    if coverage:
        html+='<p>源绘制范围：'+e(coverage.get('covered',0))+' / '+e(coverage.get('source_numeric_draws',0))+'。这仅表示基础绘制范围覆盖，动态状态尚未还原。</p>'
    html+='<p>来源网格保留在任务的 models 文件夹。未确定的身体不会作为可用裸模输出。</p></section>'
    if previews:html+='<section><h2>本次预览</h2>'+previews+'</section>'
    if alternatives:html+='<section><h2>源状态候选</h2><p>互斥版本分别保留；多个候选不会自动混合成一个身体。</p><ol>'+alternatives+'</ol></section>'
    html+='<section><h2>部件与选择依据</h2><div class="scroll"><table><thead><tr><th>部件</th><th>来源标签</th><th>判断</th><th>来源条件</th></tr></thead><tbody>'+parts+'</tbody></table></div></section>'
    html+='<section><h2>详细记录</h2><p><a href="pipeline-result.json">任务结果</a> · <a href="body-decision.json">身体判断</a>'
    if (run/'body-candidates.json').exists():html+=' · <a href="body-candidates.json">全部候选依据</a>'
    html+=' · <a href="body-analysis.log">检查日志</a></p></section></main></html>'
    path=run/'body-review.html';path.write_text(html,encoding='utf-8');return path
