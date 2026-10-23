import { useState, useEffect, useLayoutEffect, useMemo, useRef, useDeferredValue, memo, type ReactNode } from 'react';
import { Button, IconButton, TextField, Select, Dialog, Tabs, Tooltip, TextArea, SegmentedControl, Checkbox, Spinner } from '@radix-ui/themes';
import { motion, AnimatePresence, LayoutGroup, useReducedMotion } from 'motion/react';
import { BookOpen, PanelLeftClose, PanelLeftOpen, Search, ArrowUpRight, ChevronDown, ChevronRight, ChevronLeft, Check, Copy, ExternalLink, FileText, Braces, Link2, ListFilter, X, RefreshCw, Download, CircleAlert, CheckCheck, MessageSquare, Keyboard, Pin, ArrowLeft, HelpCircle, FolderOpen } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import type { Dataset, Block, Claim, Category, Evidence, PersonalNote, Preview } from './types';
import { paragraphBounds } from './selectionGeometry';

const LABELS:Record<Category,string> = { reviewed:'已有核查', pending:'待核读', partial:'部分支持', conflict:'核查冲突', issue:'核查失败', conflict_checked:'已查直接冲突' };
const NOTE_LABELS = { unreviewed:'未检查', checked:'我已检查', question:'有疑问', flag:'需处理' };
const TYPE_LABELS:Record<string,string> = { numeric:'数值断言',method_or_definition:'方法与定义', research_question_or_contribution:'研究陈述', literature_claim:'文献陈述',assertion:'原子命题', empirical_result:'实证结果',interpretation:'解释与推论', bibliographic_field:'著录字段',bibliographic_metadata:'文献著录',reported_result:'报告结果',table_cell:'表格断言',figure_claim:'图注断言',background_or_literature:'背景与文献',scope_and_limitation:'范围与局限',declaration_or_provenance:'声明与来源',practical_implication:'实际应用' };
const norm = (s:string) => s.replace(/\s+/g,' ').trim().toLocaleLowerCase();
const MOVE_EASE = [.25,1,.5,1] as const;
const SELECTION_TRANSITION = {type:'tween' as const,duration:.24,ease:MOVE_EASE};

function ParagraphSelection({selected,raw,containerRef}:{selected:string;raw:boolean;containerRef:{current:HTMLDivElement|null}}) {
  const reduce=useReducedMotion();
  const [bounds,setBounds]=useState<{x:number;y:number;width:number;height:number}|null>(null);
  useLayoutEffect(()=>{
    const paper=containerRef.current?.querySelector<HTMLElement>('.paper');
    const target=paper?.querySelector<HTMLElement>(`[data-block-id="${selected}"]`);
    if(!paper||!target){setBounds(null);return;}
    const measure=()=>{
      // Offset coordinates belong to the paper, so smooth scrolling never changes them.
      const next=paragraphBounds(target);
      setBounds(previous=>previous&&Object.keys(next).every(k=>previous[k as keyof typeof next]===next[k as keyof typeof next])?previous:next);
    };
    measure();const observer=new ResizeObserver(measure);observer.observe(paper);observer.observe(target);
    return()=>observer.disconnect();
  },[selected,raw,containerRef]);
  return bounds?<motion.div className="paragraph-selection" data-selection-for={selected} initial={false}
    animate={bounds} transition={reduce?{duration:0}:SELECTION_TRANSITION} aria-hidden="true"/>:null;
}

// Native scrolling remains interruptible by the user's wheel, touch or next target.
function revealWithin(container:HTMLElement|null, target:HTMLElement|null, reduce:boolean, align:'nearest'|'start'='start') {
  if(!container||!target)return;
  const viewport=container.getBoundingClientRect(),rect=target.getBoundingClientRect();
  if(align==='nearest'&&rect.top>=viewport.top+24&&rect.bottom<=viewport.bottom-24)return;
  container.scrollTo({top:container.scrollTop+rect.top-viewport.top-28,behavior:reduce?'instant':'smooth'});
}

function SegmentView({direction,reduce,scrollRef,children}:{direction:number;reduce:boolean;scrollRef:{current:HTMLDivElement|null};children:ReactNode}) {
  useLayoutEffect(()=>{if(scrollRef.current)scrollRef.current.scrollTop=0;},[scrollRef]);
  return <motion.div className="segment-view" custom={direction}
    variants={{enter:(d:number)=>({opacity:0,transform:`translateY(${reduce?0:d*12}px)`}),visible:{opacity:1,transform:'translateY(0px)',transition:{duration:.22,ease:MOVE_EASE}},leave:(d:number)=>({opacity:0,transform:`translateY(${reduce?0:-d*8}px)`,transition:{duration:.09,ease:MOVE_EASE}})}}
    initial="enter" animate="visible" exit="leave"
    onAnimationComplete={phase=>{if(phase==='visible')revealWithin(scrollRef.current,scrollRef.current?.querySelector('.claim.open')||null,reduce);}}>{children}</motion.div>;
}
function safeUrl(s?:string|null) { return s && /^https?:\/\//i.test(s) ? s : undefined; }
function shortPath(s?:string|null) { return s?.replaceAll('\\','/').split('/').pop() || '来源记录'; }
function niceValue(x:unknown) { return typeof x==='string' ? x : JSON.stringify(x,null,2); }
async function api<T>(url:string, options?:RequestInit):Promise<T> {
  const r = await fetch(url, options); const value=await r.json();
  if(!r.ok) throw new Error(value.error || `Request failed: ${r.status}`); return value;
}
function Tag({category}:{category:Category}) { return <span className={`verdict ${category}`}>{category==='conflict'?<CircleAlert size={12}/>:category==='pending'?null:<span className="status-mark"/>}{LABELS[category]}</span>; }
function CopyButton({value,label='复制'}:{value:string;label?:string}) {
  const [copied,setCopied]=useState(false); const timer=useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(()=>()=>clearTimeout(timer.current),[]);
  return <Button size="1" variant="ghost" color="gray" onClick={async()=>{try{await navigator.clipboard.writeText(value);setCopied(true);clearTimeout(timer.current);timer.current=setTimeout(()=>setCopied(false),1400);}catch{setCopied(false);}}}>{copied?<Check size={13}/>:<Copy size={13}/>} {copied?'已复制':label}</Button>;
}
const Markdown=memo(function Markdown({text}:{text:string}) { return <ReactMarkdown remarkPlugins={[remarkGfm,remarkMath]} rehypePlugins={[rehypeKatex]} components={{a:({href,children})=><a href={safeUrl(href)} target="_blank" rel="noreferrer noopener" onClick={e=>e.stopPropagation()}>{children}</a>}}>{text}</ReactMarkdown>; });

function EvidenceItem({ev,onOpen}:{ev:Evidence;onOpen:(ev:Evidence)=>void}) {
  const [expanded,setExpanded]=useState(false); const reduce=useReducedMotion();
  const loc=ev.locator || {}; const pdf=loc.pdf_page; const line=loc.line || loc.csv_line;
  const where=[pdf?`PDF 第 ${pdf} 页`:null,line?`第 ${line}${loc.end_line?`–${loc.end_line}`:''} 行`:null,loc.pointer || loc.json_pointer,loc.function,loc.query_id].filter(Boolean).map(String).join(' · ');
  const title = ev.localPath ? shortPath(ev.localPath) : (ev.referenceRecord?.title || ev.sourceUrl || ev.id);
  let quote=ev.quote; try{quote=JSON.stringify(JSON.parse(quote),null,2);}catch{/* Prose source quotation is kept verbatim. */}
  return <section className="evidence-item" data-od-id={`evidence-${ev.id}`}>
    <div className="evidence-meta"><span className="mono">{ev.id}</span><span>{safeUrl(ev.doiUrl)?'文献原文':'研究来源'}</span><span className={ev.localPath&&!ev.localExists?'missing':''}>{ev.localPath?(ev.localExists?'本地可访问':'本地不可访问'):(ev.sourceUrl?'在线来源':'未提供全文')}</span></div>
    <button className="evidence-title" onClick={()=>setExpanded(!expanded)} aria-expanded={expanded}>{expanded?<ChevronDown size={15}/>:<ChevronRight size={15}/>}<span>{title}</span></button>
    {where?<div className="locator mono">{where}</div>:<div className="locator">定位信息见原始记录</div>}
    <blockquote className={expanded?'quote expanded':'quote'}>{quote}</blockquote>
    <div className="evidence-actions"><Button size="1" variant="soft" color="gray" onClick={()=>onOpen(ev)}><FileText size={13}/> 核读来源</Button><CopyButton value={ev.quote} label="引文"/>{safeUrl(ev.doiUrl)?<a href={ev.doiUrl} target="_blank" rel="noreferrer noopener" className="small-link">DOI <ArrowUpRight size={12}/></a>:null}</div>
    <AnimatePresence initial={false}>{expanded?<motion.div key="locator" initial={{opacity:0,y:reduce?0:4}} animate={{opacity:1,y:0}} exit={{opacity:0}} transition={{duration:.14}} className="evidence-extra"><dl>{Object.entries(loc).map(([k,v])=><div key={k}><dt>{k}</dt><dd>{niceValue(v)}</dd></div>)}</dl>{ev.referenceRecord?.source_note?<p className="muted small">{ev.referenceRecord.source_note}</p>:null}<CopyButton value={JSON.stringify(ev,null,2)} label="完整记录"/></motion.div>:null}</AnimatePresence>
  </section>;
}

function SourceDialog({ev,onClose}:{ev:Evidence|null;onClose:()=>void}) {
  const [preview,setPreview]=useState<Preview|null>(null),[error,setError]=useState(''),[page,setPage]=useState<number|null>(null);
  useEffect(()=>setPage(null),[ev]);
  useEffect(()=>{setPreview(null);setError('');if(!ev)return;let active=true;api<Preview>(`/api/evidence/${encodeURIComponent(ev.id)}${page?`?page=${page}`:''}`).then(p=>active&&setPreview(p)).catch(e=>active&&setError(e.message));return()=>{active=false;};},[ev,page]);
  return <Dialog.Root open={Boolean(ev)} onOpenChange={o=>!o&&onClose()}><Dialog.Content className="source-dialog" maxWidth="1000px"><div className="dialog-top"><div><Dialog.Title>核读证据来源 <span className="mono muted">{ev?.id}</span></Dialog.Title><Dialog.Description className="muted small">按登记的原文位置读取；不执行研究程序或数据库查询。</Dialog.Description></div><Dialog.Close><IconButton variant="ghost" color="gray" aria-label="关闭来源"><X size={19}/></IconButton></Dialog.Close></div>
    <div className="source-location"><span className="mono">{preview?.path || ev?.sourceUrl || '已登记来源'}</span>{ev?.localPath?<CopyButton value={ev.localPath} label="路径"/>:null}</div>
    <div className="source-links">{safeUrl(ev?.doiUrl)?<a href={ev!.doiUrl} target="_blank" rel="noreferrer noopener">DOI <ArrowUpRight size={13}/></a>:null}{safeUrl(ev?.sourceUrl)?<a href={ev!.sourceUrl} target="_blank" rel="noreferrer noopener">全文入口 <ExternalLink size={13}/></a>:null}{ev?.localExists?<a href={`/api/file/${encodeURIComponent(ev.id)}${preview?.pdf?`#page=${preview.page}`:''}`} target="_blank" rel="noreferrer noopener">打开登记文件 <ArrowUpRight size={13}/></a>:null}{preview?.redaction?<span className="muted small">副本口令已隐藏 · 包内哈希已核验</span>:preview?.hashMatches===true?<span className="success small"><Check size={13}/> 文件哈希一致</span>:preview?.hashMatches===false?<span className="danger small"><CircleAlert size={13}/> 文件已变更，哈希不一致</span>:preview?.sha256?<span className="muted small">来源未登记可比较哈希</span>:null}</div>
    {!preview&&!error?<div className="loading"><Spinner/> 正在读取来源…</div>:null}{error?<p role="alert" className="danger">{error}</p>:null}{preview?.message?<p className="source-message">{preview.message}</p>:null}
    {preview?.pdf?<><div className="pdf-toolbar"><span>PDF 原页 · {preview.page} / {preview.pages}</span><div><IconButton size="1" variant="ghost" color="gray" aria-label="上一页文献" disabled={preview.page===1} onClick={()=>setPage(preview.page!-1)}><ChevronLeft size={16}/></IconButton><IconButton size="1" variant="ghost" color="gray" aria-label="下一页文献" disabled={preview.page===preview.pages} onClick={()=>setPage(preview.page!+1)}><ChevronRight size={16}/></IconButton></div></div><div className="pdf-render"><img alt={`文献 PDF 原文第 ${preview.page} 页`} src={preview.pageImage}/></div><details className="raw-record"><summary>原页提取文字</summary><pre>{preview.pdfText}</pre></details></>:preview?.text?<><div className="preview-heading">{preview.pointer?`JSON pointer: ${preview.pointer}`:preview.previewScope}</div><pre className="source-code">{preview.text}</pre>{preview.truncated?<p className="muted small">预览截至 100,000 字符。完整内容可从登记文件打开。</p>:null}</>:null}
    {ev?<details className="raw-record"><summary>已登记引文与完整定位记录</summary><pre>{JSON.stringify(ev,null,2)}</pre></details>:null}
  </Dialog.Content></Dialog.Root>;
}

function PersonalReview({claim,note,disabled,onSave}:{claim:Claim;note?:PersonalNote;disabled:boolean;onSave:(status:PersonalNote['status'],note:string)=>Promise<void>}) {
  const [text,setText]=useState(note?.note||''),[status,setStatus]=useState<PersonalNote['status']>(note?.status||'unreviewed'),[saving,setSaving]=useState(false),[saved,setSaved]=useState(false),[error,setError]=useState('');
  useEffect(()=>{setText(note?.note||'');setStatus(note?.status||'unreviewed');setSaved(false);setError('');},[claim.key,note]);
  return <section className="personal-review"><div className="section-line"><h3><MessageSquare size={15}/> 我的检查</h3><span className="muted small">独立备注，不改变核验结论</span></div><div className="review-select"><Select.Root value={status} onValueChange={v=>{setStatus(v as PersonalNote['status']);setSaved(false);}} disabled={disabled}><Select.Trigger aria-label="我的检查状态"/><Select.Content>{Object.entries(NOTE_LABELS).map(([k,v])=><Select.Item key={k} value={k}>{v}</Select.Item>)}</Select.Content></Select.Root><Button size="2" variant="soft" color="gray" disabled={disabled||saving} onClick={async()=>{setSaving(true);setError('');try{await onSave(status,text);setSaved(true);}catch(e){setError((e as Error).message);}finally{setSaving(false);}}}>{saving?<Spinner/>:saved?<Check size={14}/>:<Pin size={14}/>} {saved?'已保存':'保存检查'}</Button></div><TextArea aria-label="检查备注" placeholder="记录你的疑问、核对结果或待处理事项…" value={text} onChange={e=>{setText(e.target.value);setSaved(false);}} disabled={disabled} resize="vertical" rows={3}/>{error?<p role="alert" className="danger small">{error}</p>:null}{note?.updatedAt?<p className="muted small">保存在检查层服务器 · {new Date(note.updatedAt).toLocaleString('zh-CN')}</p>:null}</section>;
}

function ClaimDetail({claim,data,notes,goTo,onOpen,onSave}:{claim:Claim;data:Dataset;notes:Record<string,PersonalNote>;goTo:(key:string)=>void;onOpen:(ev:Evidence)=>void;onSave:(s:PersonalNote['status'],n:string)=>Promise<void>}) {
  const [tab,setTab]=useState('evidence');
  useEffect(()=>setTab('evidence'),[claim.key]);
  const related = useMemo(()=>{
    const byId=new Map<string,Claim[]>();for(const c of Object.values(data.claims)){const a=byId.get(c.claimId)||[];a.push(c);byId.set(c.claimId,a);}
    const links=data.relations.filter(r=>r.src===claim.claimId||r.dst===claim.claimId);
    return {links,byId};
  },[claim.claimId,data]);
  const reasons=claim.audit?.project_reviews || [];
  const same=related.byId.get(claim.claimId)?.filter(c=>c.key!==claim.key)||[];
  return <div className="claim-detail">
    <details className="original-sentence"><summary>原文上下文 <span className="mono">UTF-8 {claim.sentenceRanges.map(r=>`${r.start_byte}–${r.end_byte}`).join(', ')}</span></summary><p lang="en">{claim.sentence}</p></details>
    {reasons.length?<div className="review-reasons">{reasons.map((r,i)=><p key={i} className={r.status==='counterevidence'?'reason-conflict':''}>{r.reason}</p>)}</div>:claim.checks.length?<p className="review-reasons">{claim.checks.find(c=>c.kind==='scope')?.reason || claim.checks[0].reason}</p>:null}
    <Tabs.Root value={tab} onValueChange={setTab}><Tabs.List size="1"><Tabs.Trigger value="evidence">证据 <span className="tab-count">{claim.evidenceIds.length}</span></Tabs.Trigger><Tabs.Trigger value="checks">核查记录 <span className="tab-count">{claim.checks.length+claim.assessments.length}</span></Tabs.Trigger><Tabs.Trigger value="related">关联 <span className="tab-count">{related.links.length+same.length}</span></Tabs.Trigger></Tabs.List>
      <Tabs.Content value="evidence"><div className="tab-content">{claim.evidenceIds.length?claim.evidenceIds.map(id=><EvidenceItem key={id} ev={data.evidence[id]} onOpen={onOpen}/>):<div className="empty-inline"><FolderOpen size={20}/><p>此命题尚无已绑定的证据片段。</p><span>保留待核状态，不用附近的引用代替证据。</span></div>}{claim.unresolvedEvidenceIds.length?<p className="danger small">未解析证据编号：{claim.unresolvedEvidenceIds.join(', ')}</p>:null}</div></Tabs.Content>
      <Tabs.Content value="checks"><div className="tab-content"><p className="small muted">以下为账本中的实际记录，保留其方法、范围和版本。“记录通过”不代表全文全部阶段通过。</p>{claim.checks.map(c=><article className="check-record" key={c.id}><div className="section-line"><span className="mono">{c.id} · {c.kind}</span><span className={c.outcome==='conflict'?'danger':'muted'}>{c.outcome}</span></div><p>{c.reason}</p><details><summary>方法与版本</summary><p>{c.method}</p><span className="mono muted">{c.state_id}</span></details></article>)}{claim.assessments.map(a=><article className="check-record" key={a.id}><div className="section-line"><span className="mono">{a.id} → {a.evidence_id}</span><span>{a.status}</span></div><p>{a.reason}</p>{a.limitations?.map((l,i)=><p key={i} className="muted small">{l}</p>)}<span className="mono muted small">{a.state_id}</span></article>)}{Object.keys(claim.stages).length?<details className="stage-record"><summary>分阶段检查状态（原记录）</summary><dl>{Object.entries(claim.stages).map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl></details>:null}{!claim.checks.length&&!claim.assessments.length?<p className="muted">没有登记单命题检查结果。</p>:null}<details className="raw-record"><summary>查看命题原始记录</summary><pre>{JSON.stringify(claim,null,2)}</pre></details></div></Tabs.Content>
      <Tabs.Content value="related"><div className="tab-content"><p className="small muted">仅展示账本明确登记的关系与同一命题的其他位置；不按词语相似度猜测关联。</p>{same.map(c=><button className="related-link" key={c.key} onClick={()=>goTo(c.key)}><span className="small muted">同一命题 · 另一个位置</span><strong>{data.blocks.find(b=>b.id===c.blockId)?.section}</strong><span>{c.sentence.slice(0,180)}</span><ArrowUpRight size={14}/></button>)}{related.links.map(r=>{const target=r.src===claim.claimId?r.dst:r.src;const c=related.byId.get(target)?.[0];return <article className="relation-record" key={r.id}><div className="section-line"><span className="mono">{r.type}</span><span className="small muted">{r.status}</span></div>{c?<button className="related-link" onClick={()=>goTo(c.key)}><strong>{c.statement}</strong><span className="mono muted">{target} <ArrowUpRight size={12}/></span></button>:<span>{target}</span>}<p className="small">{r.reason}</p></article>;})}{!same.length&&!related.links.length?<p className="muted">当前账本没有为这一命题登记跨段关系。</p>:null}</div></Tabs.Content>
    </Tabs.Root>
    {Boolean(claim.historicalChecks?.length||claim.historicalAssessments?.length)?<details className="raw-record"><summary>历史核查（不参与当前状态）</summary>{claim.historicalEvidenceIds?.filter(id=>!claim.evidenceIds.includes(id)).map(id=><EvidenceItem key={id} ev={data.evidence[id]} onOpen={onOpen}/>)}<pre>{JSON.stringify({checks:claim.historicalChecks,assessments:claim.historicalAssessments},null,2)}</pre></details>:null}
    {claim.pendingTasks?.length?<details className="raw-record"><summary>当前待办 · {claim.pendingTasks.length}</summary><pre>{JSON.stringify(claim.pendingTasks,null,2)}</pre></details>:null}
    <PersonalReview claim={claim} note={notes[`${data.meta.sha256}:${claim.key}`]} disabled={data.live.stale} onSave={onSave}/>
  </div>;
}

function DisclosureMotion({open,children}:{open:boolean;children:ReactNode}) {
  const reduce=useReducedMotion();
  return <AnimatePresence initial={false}>{open?<motion.div key="detail" className="disclosure-motion" initial={{height:reduce?'auto':0,opacity:0}} animate={{height:'auto',opacity:1}} exit={{height:reduce?'auto':0,opacity:0}} transition={{height:{duration:reduce?0:.22,ease:MOVE_EASE},opacity:{duration:open?.16:.09}}}>{children}</motion.div>:null}</AnimatePresence>;
}

const SourceBlock=memo(function SourceBlock({block,active,select,counts}:{block:Block;active:boolean;select:(b:Block)=>void;counts:{conflict:number;pending:number}}) {
  return <div id={block.id} data-block-id={block.id} data-od-id={`paragraph-${block.id}`} className={`source-block ${active?'selected':''} ${block.kind} ${counts.conflict?'has-conflict':''}`} tabIndex={0} role="button" aria-label={`原文段落 ${block.index+1}：${block.raw.slice(0,90)}`} aria-pressed={active} onClick={()=>select(block)} onKeyDown={e=>{if((e.key==='Enter'||e.key===' ') && e.target===e.currentTarget){e.preventDefault();select(block);}}}>
    <div className="block-gutter"><span>{String(block.index+1).padStart(3,'0')}</span>{counts.conflict?<CircleAlert size={13}/>:null}</div><div className="source-text" lang="en"><Markdown text={block.raw}/></div><div className="block-indicator">{block.claimKeys.length?<span title="本段命题数">{block.claimKeys.length}</span>:null}</div>
  </div>;
});

export default function App() {
  const [data,setData]=useState<Dataset|null>(null),[notes,setNotes]=useState<Record<string,PersonalNote>>({}),[error,setError]=useState('');
  const [selected,setSelected]=useState(''),[claimKey,setClaimKey]=useState(''),[toc,setToc]=useState(true),[query,setQuery]=useState(''),[filter,setFilter]=useState('all'),[selectedText,setSelectedText]=useState(''),[source,setSource]=useState<Evidence|null>(null),[refreshing,setRefreshing]=useState(false),[raw,setRaw]=useState(false),[reviewOnly,setReviewOnly]=useState(false);
  const search=useDeferredValue(norm(query)); const readerRef=useRef<HTMLDivElement>(null),rightRef=useRef<HTMLDivElement>(null);
  const reduce=Boolean(useReducedMotion());const [direction,setDirection]=useState(1);
  const initialLoad=async()=>{const [d,n]=await Promise.all([api<Dataset>('/api/data'),api<Record<string,PersonalNote>>('/api/notes')]);setData(d);setNotes(n);return d;};
  useEffect(()=>{initialLoad().then(d=>{const hash=decodeURIComponent(location.hash.slice(1));const c=Object.values(d.claims).find(c=>c.claimId===hash);const block=c?d.blocks.find(b=>b.id===c.blockId):d.blocks.find(b=>b.claimKeys.length);setSelected((block||d.blocks[0])?.id||'');setClaimKey(c?.key||'');}).catch(e=>setError(e.message));},[]);
  useEffect(()=>{const timer=setInterval(()=>{api<Dataset['live']>('/api/status').then(l=>setData(d=>d?{...d,live:{...l,stale:l.stale||l.currentState!==d.meta.state||l.actualSha256!==d.meta.sha256||Boolean(d.meta.releaseId&&l.releaseId!==d.meta.releaseId)}}:d)).catch(()=>{});},30000);return()=>clearInterval(timer);},[]);
  const claimsByBlock=useMemo(()=>new Map(data?.blocks.map(b=>[b.id,b.claimKeys.map(k=>data.claims[k])])||[]),[data]);
  const blockCounts=useMemo(()=>new Map(data?.blocks.map(b=>[b.id,{conflict:b.claimKeys.filter(k=>data.claims[k].category==='conflict').length,pending:b.claimKeys.filter(k=>['pending','partial'].includes(data.claims[k].category)).length}])||[]),[data]);
  const blocks=useMemo(()=>data?.blocks.filter(b=>{
    const cs=claimsByBlock.get(b.id)||[];
    const filtered=filter==='all'||cs.some(c=>filter==='attention'?['pending','partial','conflict','issue'].includes(c.category):c.category===filter);
    const term=!search||norm(b.raw).includes(search)||cs.some(c=>norm(`${c.statement} ${c.claimId} ${c.propositionId}`).includes(search));
    const mine=!reviewOnly||cs.some(c=>notes[`${data.meta.sha256}:${c.key}`]?.status==='question'||notes[`${data.meta.sha256}:${c.key}`]?.status==='flag');
    return filtered&&term&&mine;
  })||[],[data,claimsByBlock,filter,search,notes,reviewOnly]);
  useEffect(()=>{
    if(!data || !blocks.length || blocks.some(b=>b.id===selected))return;
    const first=blocks[0];const cs=first.claimKeys.map(k=>data.claims[k]);
    const match=cs.find(c=>filter==='conflict'?c.category==='conflict':search?norm(`${c.statement} ${c.claimId} ${c.propositionId}`).includes(search):true);
    setSelected(first.id);setClaimKey(search&&/^c\d+$/i.test(search)?match?.key||'':'');setSelectedText('');
  },[blocks,data,selected,filter,search]);
  useEffect(()=>{
    if(!claimKey || (filter==='all'&&!search))return;
    const frame=requestAnimationFrame(()=>revealWithin(rightRef.current,rightRef.current?.querySelector('.claim.open')||null,reduce));
    return()=>cancelAnimationFrame(frame);
  },[claimKey,filter,search,reduce]);
  const activeBlock=data?.blocks.find(b=>b.id===selected);
  const paraClaims=activeBlock?.claimKeys.map(k=>data!.claims[k])||[];
  const activeClaims=selectedText?paraClaims.filter(c=>norm(c.sentence).includes(norm(selectedText))||norm(selectedText).includes(norm(c.sentence))):paraClaims;
  const headings=data?.blocks.filter(b=>b.kind==='heading' && !b.raw.startsWith('####'))||[];
  const activeHeading=headings.filter(b=>b.index<=(activeBlock?.index??-1)).at(-1);
  const navigationFrame=useRef<number|undefined>(undefined);
  useEffect(()=>()=>cancelAnimationFrame(navigationFrame.current??0),[]);
  function locateParagraph(id:string,align:'nearest'|'start') {cancelAnimationFrame(navigationFrame.current??0);navigationFrame.current=requestAnimationFrame(()=>revealWithin(readerRef.current,document.getElementById(id),reduce,align));}
  function choose(b:Block,align:'nearest'|'start'='nearest') {setDirection(b.index>=(activeBlock?.index||0)?1:-1);setSelected(b.id);setClaimKey('');setSelectedText('');history.replaceState(null,'',location.pathname);if(align==='start'||!window.getSelection()?.toString())locateParagraph(b.id,align);}
  function jump(key:string) {if(!data)return;const c=data.claims[key];setDirection((data.blocks.find(b=>b.id===c.blockId)?.index||0)>=(activeBlock?.index||0)?1:-1);setFilter('all');setQuery('');setReviewOnly(false);setSelectedText('');setSelected(c.blockId);setClaimKey(key);locateParagraph(c.blockId,'start');location.hash=c.claimId;}
  function selectBlockById(id:string) {const b=data!.blocks.find(b=>b.id===id)!;setFilter('all');setQuery('');setReviewOnly(false);choose(b,'start');}
  const selectStable=useRef(choose);selectStable.current=choose;
  const selectCallback=useMemo(()=>(b:Block)=>selectStable.current(b),[]);
  async function save(status:PersonalNote['status'],note:string,key:string) {const row=await api<PersonalNote>('/api/notes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key,sha256:data!.meta.sha256,releaseId:data!.meta.releaseId,status,note})});setNotes(n=>({...n,[`${data!.meta.sha256}:${key}`]:row}));}
  function exportNotes() {const blob=new Blob([JSON.stringify({manuscript:data!.meta,notes:Object.values(notes).filter(n=>n.sha256===data!.meta.sha256)},null,2)],{type:'application/json'});const u=URL.createObjectURL(blob);const a=document.createElement('a');a.href=u;a.download=`papercheck-review-${data!.meta.state}.json`;a.click();URL.revokeObjectURL(u);}
  function moveParagraph(dir:number) {const list=blocks.filter(b=>b.claimKeys.length);const index=activeBlock?.index??-1;const target=dir>0?list.find(b=>b.index>index):list.slice().reverse().find(b=>b.index<index);if(target)selectBlockById(target.id);}
  useEffect(()=>{function handle(e:KeyboardEvent){if((e.target as HTMLElement).closest('input,textarea,[role="dialog"],[role="combobox"]'))return;if(e.altKey&&['ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();moveParagraph(e.key==='ArrowUp'?-1:1);}}window.addEventListener('keydown',handle);return()=>window.removeEventListener('keydown',handle);});
  function inspectSelection(){const selection=window.getSelection();const text=selection?.toString().trim();if(!text||text.length<3)return;const anchor=selection?.anchorNode?.parentElement?.closest('[data-block-id]');const focus=selection?.focusNode?.parentElement?.closest('[data-block-id]');if(anchor&&focus&&anchor===focus){const id=anchor.getAttribute('data-block-id')!;setSelected(id);setSelectedText(text);setClaimKey('');}}
  if(error&&!data)return <div className="startup-error"><CircleAlert size={28}/><h1>检查层暂时无法读取数据</h1><p>{error}</p><Button onClick={()=>location.reload()}>重新加载</Button></div>;
  if(!data)return <div className="loading startup"><Spinner size="3"/> 正在读取原文与审核账本…</div>;
  const checked=Object.values(notes).filter(n=>n.sha256===data.meta.sha256&&n.status==='checked').length;
  const progress=data.meta.occurrences?Math.round(checked/data.meta.occurrences*100):0;
  return <LayoutGroup id="review-navigation"><div className={`app-shell ${toc?'':'toc-hidden'}`}>
    <header className="topbar" data-od-id="review-toolbar"><div className="brand"><BookOpen size={21} strokeWidth={1.7}/><strong>Papercheck</strong><span className="brand-divider"/><span className="muted">原文与证据</span></div><div className="topbar-actions"><span className="state-label mono">{data.meta.state}</span><Tooltip content="重新读取已登记的最新版本，不自动修改或提交论文"><Button size="2" variant="ghost" color="gray" disabled={refreshing} onClick={async()=>{setRefreshing(true);setError('');try{await api('/api/refresh',{method:'POST'});await initialLoad();}catch(e){setError((e as Error).message);}finally{setRefreshing(false);}}}><RefreshCw size={14} className={refreshing?'spinning':''}/> 刷新</Button></Tooltip>{data.meta.manuscriptPdfUrl?<Button asChild variant="ghost" color="gray" size="2"><a href={data.meta.manuscriptPdfUrl} target="_blank" rel="noreferrer noopener"><FileText size={14}/> 论文PDF</a></Button>:null}<Button variant="soft" color="gray" size="2" onClick={exportNotes}><Download size={14}/> 导出检查</Button><Dialog.Root><Dialog.Trigger><IconButton variant="ghost" color="gray" aria-label="使用说明"><HelpCircle size={18}/></IconButton></Dialog.Trigger><Dialog.Content maxWidth="560px"><Dialog.Title>从原文开始检查</Dialog.Title><Dialog.Description>阅读、定位、核读，个人意见独立保存。</Dialog.Description><ol className="help-list"><li>点击左侧段落，右侧出现全部已拆分命题。</li><li>展开命题，核对原句、引文和精确来源。拖选同段文字可按原句筛选。</li><li>“核读来源”展示登记行、JSON pointer 或 PDF 原页；DOI 和全文入口单独打开。</li><li>关联页仅展示明确登记的关系。待核读不等于错误。</li><li>保存“我的检查”不会改写论文、审核结论或原始账本。</li></ol><p className="muted small">已有核查 / 已查直接冲突 / 部分支持 / 待核读 / 直接反证分别保留原有含义。核验阶段详见每条命题的记录。</p><p><Keyboard size={14}/> Alt + ↑ / ↓ 切换到上一／下一段</p><Dialog.Close><Button variant="soft" color="gray">知道了</Button></Dialog.Close></Dialog.Content></Dialog.Root></div></header>
    {(data.live.stale||error)?<div className="global-warning" role="alert"><CircleAlert size={15}/>{data.live.stale?'原文或账本已有新版本。当前展示冻结版本，个人检查保存已暂停；先登记新稿，再刷新。':error}<button aria-label="关闭提示" onClick={()=>setError('')}><X size={14}/></button></div>:null}
    <div className="workspace">
      <aside className="outline"><div className="outline-top"><span>文稿目录</span><Tooltip content="收起目录"><IconButton aria-label="收起目录" variant="ghost" color="gray" size="1" onClick={()=>setToc(false)}><PanelLeftClose size={16}/></IconButton></Tooltip></div><motion.nav layoutScroll aria-label="论文章节">{headings.map(b=><button key={b.id} className={`${b.raw.startsWith('###')?'subheading':''} ${activeHeading?.id===b.id?'active':''}`} onClick={()=>selectBlockById(b.id)}>{activeHeading?.id===b.id?<motion.span layoutId="outline-selection" className="outline-selection" transition={reduce?{duration:0}:SELECTION_TRANSITION} style={{borderRadius:4}} aria-hidden="true"/>:null}<span className="outline-label">{b.raw.trim().replace(/^#+\s*/,'')}</span></button>)}</motion.nav><div className="outline-footer"><span className="mono">{data.meta.snapshot}</span><p>原文与账本只读<br/>个人备注独立保存</p><Tooltip content={data.meta.sha256}><span className="mono hash-short">{data.meta.sha256.slice(7,19)}…</span></Tooltip></div></aside>
      <main className="reader" aria-label="论文原文"><div className="reader-toolbar">{!toc?<IconButton size="1" variant="ghost" color="gray" aria-label="展开目录" onClick={()=>setToc(true)}><PanelLeftOpen size={16}/></IconButton>:null}<div className="reader-title"><FileText size={14}/><span>论文原文</span></div><span className="toolbar-spacer"/><TextField.Root size="2" aria-label="搜索原文或命题" value={query} onChange={e=>setQuery(e.target.value)} placeholder="搜索原文、命题或编号"><TextField.Slot><Search size={14}/></TextField.Slot>{query?<TextField.Slot><IconButton size="1" variant="ghost" color="gray" aria-label="清除搜索" onClick={()=>setQuery('')}><X size={12}/></IconButton></TextField.Slot>:null}</TextField.Root><Tooltip content={raw?'返回阅读排版':'查看原始 Markdown'}><IconButton size="1" variant={raw?'soft':'ghost'} color="gray" aria-label="原始 Markdown" onClick={()=>setRaw(!raw)}><Braces size={16}/></IconButton></Tooltip></div>
        <div className="filter-row"><Select.Root value={filter} onValueChange={setFilter}><Select.Trigger variant="ghost" aria-label="核查状态筛选"><ListFilter size={14}/><span>{filter==='all'?'全部内容':filter==='attention'?'待关注命题':LABELS[filter as Category]}</span></Select.Trigger><Select.Content><Select.Item value="all">全部内容</Select.Item><Select.Item value="conflict">核查冲突（{data.meta.categories.conflict||0}）</Select.Item><Select.Item value="issue">核查失败（{data.meta.categories.issue||0}）</Select.Item><Select.Item value="attention">待关注命题</Select.Item><Select.Item value="pending">待核读</Select.Item><Select.Item value="partial">部分支持</Select.Item><Select.Item value="reviewed">已有核查</Select.Item><Select.Item value="conflict_checked">已查直接冲突</Select.Item></Select.Content></Select.Root><label className="mine-filter"><Checkbox size="1" checked={reviewOnly} onCheckedChange={c=>setReviewOnly(c===true)}/> 我的疑问</label><span className="muted small filter-count">{blocks.length} / {data.meta.blocks} 段</span></div>
        <div className="reader-scroll" ref={readerRef} onMouseUp={()=>setTimeout(inspectSelection,0)}><div className="paper"><ParagraphSelection selected={selected} raw={raw} containerRef={readerRef}/>{blocks.length?blocks.map(b=>raw?<div key={b.id} id={b.id} data-block-id={b.id} className={`raw-source source-block ${selected===b.id?'selected':''}`} role="button" tabIndex={0} aria-label={`原始段落 ${b.index+1}`} onClick={()=>choose(b)} onKeyDown={e=>e.key==='Enter'&&choose(b)}><span className="mono muted small">{String(b.index+1).padStart(3,'0')} · L{b.line}</span><pre>{b.raw}</pre></div>:<SourceBlock key={b.id} block={b} active={selected===b.id} select={selectCallback} counts={blockCounts.get(b.id)!}/>):<div className="empty-inline"><Search size={26}/><h2>没有匹配的段落</h2><p>尝试其他关键词，或取消状态筛选。</p><Button variant="soft" color="gray" onClick={()=>{setQuery('');setFilter('all');setReviewOnly(false);}}>显示全文</Button></div>}</div></div>
      </main>
      <aside className="inspector" aria-label="命题与证据"><div className="inspector-top"><div className="section-line"><h2>段落检查</h2><div className="paragraph-nav"><Tooltip content="上一段 Alt+↑"><IconButton aria-label="上一段" size="1" variant="ghost" color="gray" onClick={()=>moveParagraph(-1)}><ChevronLeft size={16}/></IconButton></Tooltip><span className="mono small">{activeBlock?String(activeBlock.index+1).padStart(3,'0'):'—'}</span><Tooltip content="下一段 Alt+↓"><IconButton aria-label="下一段" size="1" variant="ghost" color="gray" onClick={()=>moveParagraph(1)}><ChevronRight size={16}/></IconButton></Tooltip></div></div><p className="inspector-context">{activeBlock?.section}</p><div className="inspector-summary"><span><strong>{paraClaims.length}</strong> 个命题</span><span><strong>{new Set(paraClaims.flatMap(c=>c.evidenceIds)).size}</strong> 份证据</span><span className="mono">L{activeBlock?.line}</span></div></div>
        {selectedText?<div className="selection-banner"><span>按选中文字筛选 · {activeClaims.length} 条</span><button onClick={()=>setSelectedText('')} aria-label="取消选中文字筛选"><X size={13}/></button><p>{selectedText.slice(0,140)}</p></div>:null}
        <div className="inspector-scroll" ref={rightRef}><AnimatePresence initial={false} mode="wait" custom={direction}><SegmentView key={selected} direction={direction} reduce={reduce} scrollRef={rightRef}>{activeClaims.length?activeClaims.map((c,i)=><section key={c.key} className={`claim ${claimKey===c.key?'open':''}`} data-od-id={`claim-${c.claimId}`}><button className="claim-trigger" aria-expanded={claimKey===c.key} onClick={()=>{setClaimKey(claimKey===c.key?'':c.key);if(claimKey!==c.key)history.replaceState(null,'',`#${c.claimId}`);else history.replaceState(null,'',location.pathname);}}><div className="claim-index mono">{String(i+1).padStart(2,'0')}</div><div className="claim-label"><div className="section-line"><span className="mono muted small">{c.claimId}</span><Tag category={c.category}/></div><h3>{c.statement}</h3><span className="claim-type">{TYPE_LABELS[c.type]||c.type}</span></div><ChevronDown size={15} className="expand-icon" style={{transform:claimKey===c.key?'rotate(180deg)':undefined}}/></button><DisclosureMotion open={claimKey===c.key}><ClaimDetail key={c.key} claim={c} data={data} notes={notes} goTo={jump} onOpen={setSource} onSave={(s,n)=>save(s,n,c.key)}/></DisclosureMotion></section>):<div className="empty-state"><BookOpen size={28} strokeWidth={1.3}/><h3>{selectedText?'未找到对应的已登记原句':(activeBlock?.tracked===false?'此处尚未纳入跟踪':'本段没有命题绑定')}</h3><p>{selectedText?'可取消文字筛选，查看本段全部命题。':(activeBlock?.tracked===false?'保留原文；需回到账本登记或明确排除后重新导出。':'查看工作流任务，区分已登记非命题内容与尚未拆分的正文。')}</p></div>}</SegmentView></AnimatePresence></div>
        <div className="inspector-foot"><Link2 size={13}/><span>绑定 ≠ 核验通过 · 核查范围见各命题记录</span></div>
      </aside>
    </div>
    <footer className="statusbar"><span className="status-left"><span className="local-indicator"/> 本地检查层 <span className="mono">{data.meta.state}</span><span className="status-separator">/</span>工作流：{data.meta.workflowStatus||'pending'} · {data.meta.pendingTasks||0} 项待办 · {data.meta.occurrences.toLocaleString()} 个命题位置 · {data.meta.claims.toLocaleString()} 个独立命题</span><span className="personal-progress"><CheckCheck size={14}/> 我的检查 {checked} / {data.meta.occurrences}<span className="progress-track"><span style={{width:`${progress}%`}}/></span></span></footer>
    <SourceDialog ev={source} onClose={()=>setSource(null)}/>
  </div></LayoutGroup>;
}
