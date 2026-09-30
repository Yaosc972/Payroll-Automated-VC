// Synthetic upstream only. Run locally for browser/API end-to-end regression.
import http from "node:http";
import { BeisenClient } from "../../lib/beisen-client.mjs";
import { syncCandidates, listSubjects } from "../../lib/service.mjs";

process.env.BEISEN_APP_KEY = "fixture";
process.env.BEISEN_APP_SECRET = "fixture";
delete process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_GZIP_BASE64;
const names = ["正常入职测试", "审批中离职测试", "重新入职测试", "撤回离职测试", "15日前自愿测试", "15日前非自愿测试", "BP指定购买测试"];
const employees = names.map((name, i) => ({
  employeeInfo: {userID:i+1, name, iDNumber:`TEST-ID-00${i+1}`, gender:"女", nation:"汉",
    mobilePhone:"13800000000", educationLevel:"大学本科", birthplace:"广东省深圳市",
    residenceAddress:"广东省深圳市南山区科技园", customProperties:{
      extsocno_109025_273047989:"123456789", extRADD3_109025_721488871:"广东省深圳市南山区科技园",
      extnowadd_109025_1438726230:"广东省深圳市南山区科技园", extshifoushixuniyuangong_109025_1767668301:"否"}},
  recordInfoList:[{employType:"内部员工",entryDate:"2026-09-03",employeeStatus:"试用",place:"深圳",
    jobNumber:`TEST-00${i+1}`,modifiedTime:"2026-09-10T12:00:00+08:00"}],
}));
const resignations = [
  {userID:2,businessTypeOID:"5",approvalStatus:1,lastWorkDate:"2026-09-10",translateProperties:{ApprovalStatusText:"审批中"}},
  {userID:3,businessTypeOID:"5",approvalStatus:4,lastWorkDate:"2026-07-01",translateProperties:{ApprovalStatusText:"生效"}},
  {userID:4,businessTypeOID:"5",approvalStatus:9,lastWorkDate:"2026-09-10",translateProperties:{ApprovalStatusText:"已撤回"}},
  ...[5, 6, 7].map(userID => ({userID, businessTypeOID:"5", approvalStatus:1,
    lastWorkDate:"2026-09-14", translateProperties:{ApprovalStatusText:"审批中"},
    customProperties:{extshifouziyuantingbao_109025_28464420:userID === 6 ? "非自愿停保" : "自愿停保"}})),
];
function client() {
  return new BeisenClient({fetchImpl: async (url, options) => {
    const body = JSON.parse(options.body);
    if (url.endsWith("/token")) return Response.json({access_token:"fixture"});
    let data;
    if (url.endsWith("/Employee/GetListByTimeWindow")) data=employees;
    else if (url.endsWith("/Contract/GetByUserIds")) data={rows:employees.map(r=>({userID:r.employeeInfo.userID,firstParty:"深圳测试主体",firstPartyCode:"SZ001"}))};
    else if (url.endsWith("/Offer/GetByTimeWindow")) data=[];
    else if (url.endsWith("/Employee/GetServiceInfoByIds")) {
      if (body.option !== "None" || !body.approvalStatus.includes("Approving") || !body.approvalStatus.includes("Effective")) throw new Error("approval filter regression");
      data=resignations.filter(r=>body.oIds.includes(r.userID));
    } else throw new Error("Unexpected fixture endpoint");
    return Response.json({code:"200",data,isLastData:true});
  }});
}
http.createServer(async (req,res)=>{
  try {
    let raw=""; for await(const chunk of req) raw+=chunk;
    const payload=JSON.parse(raw||"{}");
    const value=req.url.endsWith("subjects") ? await listSubjects(payload,{client:client()})
      : await syncCandidates(payload,{client:client()});
    res.writeHead(200,{"content-type":"application/json"});res.end(JSON.stringify(value));
  } catch(error) {res.writeHead(502);res.end(JSON.stringify({error:error.message}));}
}).listen(Number(process.argv[2]||18012),"127.0.0.1",()=>console.log("synthetic connector ready"));
