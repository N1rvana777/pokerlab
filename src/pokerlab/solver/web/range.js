// Range text semantics match the pinned engine: earlier entries override later ones.
// Keep blocked combinations in the input; exclude them only from effective counts.
const RangeEditor = (() => {
  const ranks='23456789TJQKA', suits='cdhs';
  function single(text) {
    let a,b,kind;
    if (/^[2-9TJQKA][cdhs][2-9TJQKA][cdhs]$/.test(text)) {
      a=ranks.indexOf(text[0]);b=ranks.indexOf(text[2]);kind=text[1]+text[3];
      if(a===b&&kind[0]===kind[1])throw Error('重复牌：'+text);
    } else if (/^[2-9TJQKA]{2}[so]?$/.test(text)) {
      a=ranks.indexOf(text[0]);b=ranks.indexOf(text[1]);kind=text[2]||'';
      if(a===b&&kind)throw Error('对子不能指定 s/o：'+text);
    } else throw Error('无法解析范围：'+text);
    if(a<b)throw Error('请把较高点数写在前面：'+text);
    return [a,b,kind];
  }
  function combos([a,b,kind]) {
    const out=[];
    for(let x=0;x<4;x++)for(let y=0;y<4;y++) {
      if(a===b&&x>=y)continue;
      if(kind==='s'&&x!==y||kind==='o'&&x===y)continue;
      if(kind.length===2 && !(suits[x]===kind[0]&&suits[y]===kind[1] || a===b&&suits[y]===kind[0]&&suits[x]===kind[1]))continue;
      out.push(ranks[a]+suits[x]+ranks[b]+suits[y]);
    }
    return out;
  }
  function parse(text) {
    const result=new Map(),tokens=text.trim().split(',');
    if(tokens.at(-1).trim()==='')tokens.pop();
    for(const token of tokens.reverse()) {
      const parts=token.trim().split(':');
      if(parts.length>2||parts.length===2&&!/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(parts[1].trim()))throw Error('权重格式错误：'+token);
      const weight=parts.length===2?Number(parts[1]):1, spec=parts[0].trim();
      if(!Number.isFinite(weight)||weight<0||weight>1)throw Error('权重必须在 0–1：'+token);
      let hands=[];
      if(spec.endsWith('+')) {
        const [a,b,k]=single(spec.slice(0,-1)),gap=a-b;
        if(gap<=1)for(let i=a;i<13;i++)hands.push([i,i-gap,k]);
        else for(let i=b;i<a;i++)hands.push([a,i,k]);
      } else if(spec.includes('-')) {
        const endpoints=spec.split('-');if(endpoints.length!==2)throw Error('区间格式错误：'+spec);
        const [a,b,k]=single(endpoints[0].trim()),[c,d,l]=single(endpoints[1].trim());
        if(k!==l)throw Error('区间花色类型不一致：'+spec);
        if(a-b===c-d&&a>c)for(let i=c;i<=a;i++)hands.push([i,i-a+b,k]);
        else if(a===c&&b>d)for(let i=d;i<=b;i++)hands.push([a,i,k]);
        else throw Error('区间必须降序且同间隔或同首张：'+spec);
      } else hands=[single(spec)];
      for(const hand of hands)for(const combo of combos(hand))result.set(combo,weight);
    }
    return result;
  }
  function serialize(weights) {
    // Compact uniform groups; retain exact suit weights for nonuniform groups.
    const out=[];
    for(let a=12;a>=0;a--)for(let b=a;b>=0;b--)for(const kind of a===b?['']:['s','o']) {
      const list=combos([a,b,kind]),values=list.map(c=>weights.get(c)||0);
      if(values.every(v=>v===values[0])) {
        if(values[0]>0)out.push(ranks[a]+ranks[b]+kind+(values[0]===1?'':':'+values[0]));
      } else list.forEach((c,i)=>{if(values[i]>0)out.push(c+(values[i]===1?'':':'+values[i]))});
    }
    return out.join(',');
  }
  const blocked=(combo,board)=>board.includes(combo.slice(0,2))||board.includes(combo.slice(2));
  // Deterministic preflop engineering template, not measured equity or a
  // board-dependent equilibrium range. Every class uses equal suit weights.
  function strength([a,b,kind]) {
    const hi=a+2,lo=b+2,highScore=({14:10,13:8,12:7,11:6})[hi]??hi/2;
    if(a===b)return Math.max(5,highScore*2);
    const gap=hi-lo-1,penalty=gap<=0?0:gap===1?1:gap===2?2:gap===3?4:5;
    return highScore+(kind==='s'?2:0)-penalty+(hi<=11&&gap<=1?1:0);
  }
  const ranked=[];
  for(let a=12;a>=0;a--)for(let b=a;b>=0;b--)for(const kind of a===b?['']:['s','o']) {
    const name=ranks[a]+ranks[b]+kind;
    ranked.push({name,score:strength([a,b,kind]),count:combos([a,b,kind]).length,a,b,kind});
  }
  ranked.sort((x,y)=>y.score-x.score||y.a-x.a||y.b-x.b||x.kind.localeCompare(y.kind));
  function fromPercent(percent) {
    if(typeof percent!=='number'||!Number.isFinite(percent)||percent<0||percent>100)throw Error('总范围百分比必须在 0–100');
    const result=new Map();let remaining=1326*percent/100;
    for(const item of ranked) {
      if(remaining<=1e-10)break;
      const weight=Number(Math.min(1,remaining/item.count).toFixed(12));
      for(const combo of combos(single(item.name)))result.set(combo,weight);
      remaining-=item.count*weight;
    }
    return result;
  }
  const mass=weights=>[...weights.values()].reduce((sum,value)=>sum+value,0);
  return {parse,serialize,combosFor:name=>combos(single(name)),blocked,fromPercent,mass,
    ranking:()=>ranked.map(({name,score,count})=>({name,score,count})),
    rankingDescription:'翻前启发式模板：高牌分 A=10、K=8、Q=7、J=6，其他点数÷2；对子分×2且至少5；同花+2；隔1/2/3/≥4张扣1/2/4/5；J及以下连张或隔1张+1。平分按高牌、低牌、同花排序。对子6、同花4、非同花12，边界牌类全部花色同一混合权重。不是实测equity、翻前均衡或当前街GTO；不依据公共牌重排。'};
})();
