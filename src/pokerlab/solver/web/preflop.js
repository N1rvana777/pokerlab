// Preflop walk: click a line seat by seat; a closed line fills the scene, which stays editable before solving.
const walkDepths=[[100,'$500'],[150,'$750'],[200,'$1000'],[400,'$2000']];
const walkRanks='AKQJT98765432';
const walkState={books:[],book:null,path:[],line:null,end:null};
const walkEl={depths:el('div',undefined,'walk-depths'),seats:el('div',undefined,'walk-seats'),grid:el('div',undefined,'walk-grid'),ranges:el('div',undefined,'walk-ranges'),side:el('div',undefined,'walk-side')};
const walkControls=el('div',undefined,'toolbar walk-head');
const walkBack=el('button','后退'),walkReset=el('button','重置');walkBack.type=walkReset.type='button';walkBack.id='walk-back';walkReset.id='walk-reset';
walkControls.append(walkEl.depths,walkBack,walkReset);
walkEl.seats.id='walk-seats';walkEl.grid.id='walk-grid';walkEl.ranges.id='walk-ranges';walkEl.side.id='walk-side';
const walkBody=el('div',undefined,'walk-body');walkBody.append(walkEl.grid,walkEl.ranges,walkEl.side);
$('preflop-walk').append(walkControls,walkEl.seats,walkBody);
const walkKey=tokens=>tokens.join('-');
function walkColors(actions){
  // Same shades as the postflop strategy: larger raises are darker and the all-in is the largest.
  const names=actions.map(a=>a.code==='RAI'?'Allin(999999)':a.code?.startsWith('R')?`Raise(${a.code.slice(1)})`:a.code==='C'?'Call':a.code==='X'?'Check':'Fold');
  return names.map((name,i)=>actionStyle(name,i,names,{}));
}

function walkSettle(){
  // Seats with nothing but a fold on any captured line step aside by themselves.
  while(walkState.book.nodes[walkKey(walkState.path)]?.forced)walkState.path.push('F');
  const line=walkState.book.lines[walkKey(walkState.path)]??null;
  if(line&&line!==walkState.line)walkApply(line);
  walkState.line=line;walkState.end=walkState.book.ends?.[walkKey(walkState.path)]??null;
}
function walkApply(line){
  $('amount-unit').value='bb';refreshAmountUnit();
  $('pot').value=line.pot;$('stack').value=line.stack;$('range0').value=line.oop;$('range1').value=line.ip;
  changed();refreshEditors();
}
const walkEdited=()=>{const l=walkState.line;return !!l&&(+$('pot').value!==l.pot||+$('stack').value!==l.stack||$('range0').value.trim()!==l.oop||$('range1').value.trim()!==l.ip)};
function walkOpen(depth){
  walkState.book=walkState.books.find(b=>b.depth===depth);walkState.path=[];walkState.line=null;
  walkSettle();walkRender();
}
function walkTake(at,code){walkState.path=[...walkState.path.slice(0,at),code];walkSettle();walkRender()}
function walkUndo(){
  // Stepping back skips the folds that were taken automatically.
  const nodes=walkState.book.nodes,path=[...walkState.path];
  do path.pop();while(path.length&&nodes[walkKey(path)]?.forced);
  walkState.path=path;walkState.line=null;walkSettle();walkRender();
}
function walkCard(tokens,at,active){
  const n=walkState.book.nodes[walkKey(tokens.slice(0,at))],chosen=walkState.path[at],card=el('div',undefined,'walk-seat'+(active?' active':'')+(n.forced?' forced':''));
  card.dataset.seat=n.seat;card.append(el('div',`${n.seat} ${fmt(n.stack,1).replace(/\.0$/,'')}`,'walk-seat-name'));
  for(const a of n.actions){
    if(n.forced)continue;
    const b=el('button',a.label);b.type='button';b.dataset.code=a.code??'';b.disabled=!a.next;if(a.note)b.title=a.note;
    if(chosen===a.code)b.setAttribute('aria-pressed','true');
    if(a.next)b.onclick=()=>walkTake(at,a.code);
    card.append(b);
  }
  if(n.forced)card.append(el('small','Fold'));
  return card;
}
function walkSeats(){
  const path=walkState.path,cards=path.map((_,at)=>walkCard(path,at,false)),current=walkState.book.nodes[walkKey(path)];
  if(current)cards.push(walkCard(path,path.length,true));
  for(const seat of current?.pending.slice(1)??[]){const c=el('div',undefined,'walk-seat waiting');c.append(el('div',seat,'walk-seat-name'));cards.push(c)}
  const flop=el('div',undefined,'walk-seat walk-flop'+(walkState.line?' active':''));
  flop.append(el('div',walkState.end?'结束':'FLOP','walk-seat-name'));
  if(walkState.line){const b=el('button','选公共牌');b.type='button';b.onclick=()=>$('choose-board').click();flop.append(el('small',`底池 ${walkState.line.pot}bb · ${$('board').value||'未选'}`),b)}
  cards.push(flop);walkEl.seats.replaceChildren(...cards);walkEl.seats.scrollLeft=walkEl.seats.scrollWidth;
}
function walkCells(paint){
  const cells=[];
  walkRanks.split('').forEach((a,row)=>walkRanks.split('').forEach((b,col)=>{
    const name=row===col?a+b:row<col?a+b+'s':b+a+'o',cell=el('div',name,'walk-cell');
    cell.dataset.hand=name;paint(cell,name);cells.push(cell);
  }));
  return cells;
}
function walkGrid(n){
  walkEl.grid.hidden=!n;
  const colors=n&&walkColors(n.actions);
  if(n)walkEl.grid.replaceChildren(...walkCells((cell,name)=>{
    const shares=n.hands?.[name];
    if(!shares){cell.classList.add('unreached');return}
    cell.style.background=strategyGradient(shares,colors);
    cell.title=name+' · '+n.actions.map((x,i)=>`${x.label} ${fmt(shares[i]*100,1)}%`).join(' · ');
  }));
}
function walkClassWeights(text){
  const sums={};
  try{for(const [combo,weight] of RangeEditor.parse(text)){const name=combo[0]===combo[2]?combo[0]+combo[2]:combo[0]+combo[2]+(combo[1]===combo[3]?'s':'o');sums[name]=(sums[name]||0)+weight}}catch{return sums}
  return Object.fromEntries(Object.entries(sums).map(([name,sum])=>[name,sum/(name.length===2?6:name.endsWith('s')?4:12)]));
}
function walkRangePanel(title,text){
  const weights=walkClassWeights(text),panel=el('div'),grid=el('div',undefined,'walk-grid');
  grid.replaceChildren(...walkCells((cell,name)=>{
    const w=weights[name]||0;
    if(!w){cell.classList.add('unreached');return}
    cell.style.background=`linear-gradient(to right,${palette.Call} ${w*100}%,#101b25 ${w*100}%)`;cell.title=`${name} · ${fmt(w*100,1)}%`;
  }));
  panel.append(el('h3',title),grid);return panel;
}
function walkRanges(){
  const l=walkState.line;walkEl.ranges.hidden=!l;
  if(l)walkEl.ranges.replaceChildren(walkRangePanel(`OOP · ${l.oop_seat}`,$('range0').value),walkRangePanel(`IP · ${l.ip_seat}`,$('range1').value));
  walkBody.classList.toggle('closed',!!l);
}
function walkLibrary(line){
  const box=el('div',undefined,'toolbar walk-library'),pick=el('select');box.id='walk-library';pick.id='walk-library-pick';
  for(const item of libraryItems.filter(i=>i.kind==='range'))pick.append(new Option(item.name,item.id));
  const save=seat=>{const b=el('button',`保存 ${seat?'IP':'OOP'} 范围`);b.type='button';b.onclick=()=>guard(async()=>{await api('/api/library',{kind:'range',name:`${line.label} ${seat?line.ip_seat:line.oop_seat}`,value:$('range'+seat).value.trim()});await refreshLibrary();walkRender()});return b};
  const use=seat=>{const b=el('button',`用于 ${seat?'IP':'OOP'}`);b.type='button';b.disabled=!pick.options.length;b.onclick=()=>{const item=libraryItems.find(i=>i.id===pick.value);if(!item)return;captureEdit();$('range'+seat).value=item.value;changed();refreshEditors();captureEdit()};return b};
  box.append(save(0),save(1),pick,use(0),use(1));
  return box;
}
function walkSide(n){
  const out=[];
  if(n){
    const cards=el('div',undefined,'action-cards'),colors=walkColors(n.actions);
    n.actions.forEach((a,i)=>{
      const card=el('button',undefined,'action-card');card.type='button';card.style.background=colors[i];card.style.flexGrow=String(Math.max(.18,a.frequency??.5));card.dataset.code=a.code??'';card.disabled=!a.next;if(a.note)card.title=a.note;
      card.append(el('span',a.label,'action-card-name'),el('strong',fmt(a.frequency*100,1)+'%'),el('small',fmt(a.combos,1)+' combos'));
      if(a.next)card.onclick=()=>walkTake(walkState.path.length,a.code);
      cards.append(card);
    });
    out.push(el('p',`${n.seat} 行动 · 底池 ${fmt(n.pot,1)}bb · 需跟注 ${fmt(n.to_call,1)}bb · 后手 ${fmt(n.stack,1)}bb`),cards);
    if(!walkState.book.complete)out.push(el('p','频率由抄下来的范围算出。Fold 这一档包含没有抄录的动作（limp、全下、4bet）。','hint'));
  }
  if(walkState.end)out.push(el('p',walkState.end.text,'walk-end'));
  const l=walkState.line;
  if(l){
    out.push(el('h3',l.label));
    out.push(el('p',`底池 ${l.pot}bb，有效 ${l.stack}bb。OOP = ${l.oop_seat}（${fmt(l.oop_combos,1)} 组合），IP = ${l.ip_seat}（${fmt(l.ip_combos,1)} 组合）。`));
    out.push(el('p','双方范围、底池和筹码已填入左侧。解算前可以在左侧改范围、下注尺寸、抽水和精度。','hint'));
    const tools=el('div',undefined,'toolbar'),solveNow=el('button','开始解算','primary');solveNow.type='button';solveNow.id='walk-solve';solveNow.onclick=()=>{$('baseline').click();$('status').scrollIntoView({block:'start'})};tools.append(solveNow);
    if(walkEdited()){
      const restore=el('button','恢复这条线');restore.type='button';restore.onclick=()=>{walkApply(l);walkRender()};
      out.push(el('p','左侧已手动修改，解算用的是修改后的内容。','walk-edited'));tools.append(restore);
    }
    out.push(tools,walkLibrary(l));
  }
  if(walkState.book?.note)out.push(el('p',walkState.book.note,'hint'));
  walkEl.side.replaceChildren(...out);
}
function walkDepthButtons(){
  walkEl.depths.replaceChildren(...walkDepths.map(([depth,money])=>{
    const book=walkState.books.find(b=>b.depth===depth),b=el('button',`${depth}bb（约 ${money}）`);
    b.type='button';b.dataset.depth=depth;b.disabled=!book;if(!book)b.title='这个深度还没有抄录';
    if(walkState.book?.depth===depth)b.setAttribute('aria-pressed','true');
    if(book)b.onclick=()=>walkOpen(depth);
    return b;
  }));
}
function walkRender(){
  walkDepthButtons();
  if(!walkState.book){walkEl.side.replaceChildren(el('p','未找到范围库：outputs/gtow-preflop/ 下没有文件（这些文件不进 Git）。','hint'));return}
  walkBack.disabled=!walkState.path.length;walkSeats();
  const n=walkState.book.nodes[walkKey(walkState.path)];
  walkGrid(n);walkRanges();walkSide(n);
}
const walkLineEdited=()=>{if(walkState.line){walkSeats();walkRanges();walkSide(null)}};
walkBack.onclick=walkUndo;
walkReset.onclick=()=>walkOpen(walkState.book.depth);
const changedBeforeWalk=changed;
changed=function(){changedBeforeWalk();walkLineEdited()};
$('scenario').addEventListener('input',walkLineEdited);
guard(async()=>{
  walkState.books=await api('/api/preflop');
  walkState.book=walkState.books.find(b=>b.depth===150)??walkState.books[0]??null;
  if(walkState.book)walkSettle();
  walkRender();
});
