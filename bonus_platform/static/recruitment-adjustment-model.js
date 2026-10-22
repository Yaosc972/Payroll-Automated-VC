(function(root){
  'use strict';
  function signedAmount(value,direction){
    const amount=Number(value);
    if(!Number.isFinite(amount)||amount<=0)throw new Error('请填写大于 0 的金额');
    if(!['supplement','deduct'].includes(direction))throw new Error('请选择补发或扣回');
    return direction==='deduct'?-amount:amount;
  }
  function adjustment(values){
    return {...values,amount:signedAmount(values.amount,values.direction),type:'adjustment'};
  }
  const api={signedAmount,adjustment};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.RecruitmentAdjustmentModel=api;
})(typeof window==='undefined'?globalThis:window);
