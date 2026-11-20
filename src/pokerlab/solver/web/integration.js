// Keep the Solver assistant in the same application and current edit history.
function sameSolverInputs(a,b){
  const ordered=value=>Array.isArray(value)?value.map(ordered):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,ordered(value[key])])):value;
  const inputs=config=>{
    const scene=sceneOf(config);
    scene.raises=Array.from({length:3},(_,index)=>config.raises?.[index]??'');
    return {...scene,amount_unit:config.amount_unit??'chips',mode:config.mode,
      profile:{...config.profile,traits:config.profile?.traits??[],overrides:config.profile?.overrides??[]},target:config.target,target_unit:config.target_unit,
      max_iterations:config.max_iterations,compression:config.compression??false,
      auto_suits:config.auto_suits??false,expand_suits:config.expand_suits??false};
  };
  return JSON.stringify(ordered(inputs(a)))===JSON.stringify(ordered(inputs(b)));
}
window.PokerlabAgent?.mount({
  ready: initialSceneReady,
  readConfig: mode => getConfig(mode),
  applyConfig: config => {
    if (typeof captureEdit === 'function') captureEdit();
    setConfig(config);
    if (typeof captureEdit === 'function') captureEdit();
  },
  showResult: async (report,context={}) => {
    if (!report || !report.precision || !report.config) return;
    result = report;
    path = [];
    selected = null;
    stale = !sameSolverInputs(getConfig(context.config?.mode??report.config.mode), report.config);
    $('stale').textContent = stale ? '助手结果对应较早局面，当前输入已改变' : '';
    $('variant').value = report.config.mode === 'equilibrium' ? 'baseline' : report.config.mode === 'preview' ? 'model' : 'response';
    renderSummary();
    await guard(showNode);
  }
});
