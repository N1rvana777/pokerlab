// Flop report: the current tree on many boards, with the root numbers side by side.
const reportPresetBoards=['Ks7d2c','As8d3c','Qh7d2c','Jc6d2h','Td5c2h','9d5c2h','8d4c2h','7d4c2h','Ks7s2c','As8s3c','Qh7h2c','Jh6h2c','Th9h8c','9h8h7c','8h7h6c','KsKd7c','AsAd5c','7s7d2c','2s2d7c','Th9d8c','9h8d7c','8h7d6c','JhTd9c','QhJdTc','AhKdQc','Ks7s2s','Th9h4h','8s7s3s','7s7d7c'];
const reportPanel=el('details');reportPanel.id='report-panel';reportPanel.append(el('summary','多牌面报告'));
const reportBoards=el('textarea');reportBoards.id='report-boards';reportBoards.rows=3;reportBoards.value=reportPresetBoards.join(' ');
const reportStart=el('button','开始报告');reportStart.type='button';reportStart.id='report-start';
const reportOut=el('div',undefined,'runout-report');reportOut.id='report-out';
reportPanel.append(el('p','用左侧当前的范围、底池和下注树，逐个翻牌求均衡基线，把根节点的数字放在一起看。每个翻牌的时间和单次解算相同，下注树越小越快。默认 29 个翻牌覆盖高低牌、同花、对子和连张。结果按配置保留，中断后再开始会跳过已完成的翻牌。','hint'),reportBoards,reportStart,reportOut);
$('sensitivity-panel').after(reportPanel);
phases.flop_report='多牌面报告';
let reportRows=[],reportOrder=null;
function drawReport(){
  const u=unitOf(getConfig('equilibrium')),names=[...new Set(reportRows.flatMap(r=>r.actions))],share=(r,name)=>{const i=r.actions.indexOf(name);return i<0?undefined:r.frequencies[i]};
  const columns=[['翻牌',r=>r.board],...names.map(name=>[actionLabel(name),r=>share(r,name)]),['OOP EV ('+u+')',r=>r.seats[0].ev],['IP EV ('+u+')',r=>r.seats[1].ev],['OOP Equity',r=>r.seats[0].equity],['IP Equity',r=>r.seats[1].equity],['OOP EQR',r=>r.seats[0].eqr],['IP EQR',r=>r.seats[1].eqr],['精度 % 底池',r=>r.precision_pct]];
  const percent=c=>c>0&&c<=names.length||c>names.length+2&&c<=names.length+6;
  const table=el('table'),head=el('tr');table.id='report-table';
  columns.forEach(([title],c)=>{const th=el('th',title);th.dataset.sort=c;th.onclick=()=>{reportOrder=reportOrder===c?null:c;drawReport()};head.append(th)});table.append(head);
  const rows=[...reportRows];if(reportOrder)rows.sort((a,b)=>(columns[reportOrder][1](b)??-Infinity)-(columns[reportOrder][1](a)??-Infinity));
  for(const r of rows){
    const line=el('tr');line.dataset.board=r.board;line.onclick=()=>{captureEdit();$('board').value=r.board.match(/../g).join(' ');$('board').dispatchEvent(new Event('input',{bubbles:true}));changed();captureEdit()};
    columns.forEach(([,value],c)=>{const v=value(r);line.append(el('td',c===0?v:!Number.isFinite(v)?'—':percent(c)?fmt(v*100,1)+'%':fmt(v,c===columns.length-1?3:2)))});
    table.append(line);
  }
  reportOut.replaceChildren(el('p','点表头排序，点行把这个翻牌填到左侧。','hint'),table);
}
reportStart.onclick=()=>guard(async()=>{
  const boards=reportBoards.value.split(/[\s,]+/).filter(Boolean);
  const data=await runJob({kind:'flop_report',config:getConfig('equilibrium'),boards});
  reportRows=data.rows;reportOrder=null;drawReport();$('status').textContent=`多牌面报告完成，共 ${data.rows.length} 个翻牌`;
});
