import assert from "node:assert/strict";
import test from "node:test";
import { createAdminIndex, evaluateEmployee, matchAdminDivision } from "../lib/rules.mjs";

const index = createAdminIndex([
  "44.广东省", "4403.深圳市", "440301.市辖区", "440305.南山区",
  "52.贵州省", "5201.贵阳市", "520101.市辖区", "520102.南明区",
]);

test("户口地址在深圳时不被外省户籍所在地覆盖", () => {
  const result = evaluateEmployee({ householdAddress: "广东省深圳市南山区测试街道", birthplace: "贵州省贵阳市南明区" }, index);
  assert.equal(result.report["户籍"], "深圳户籍");
  assert.equal(result.report["户口所在地行政区划代码"], "440305.南山区");
  assert.equal(result.report["户口具体地址"], "广东省深圳市南山区测试街道");
});

test("户籍所在地在深圳时判深户但不改写外省户口地址，并提示人工核对", () => {
  const result = evaluateEmployee({ householdAddress: "贵州省贵阳市南明区测试街道", birthplace: "广东省深圳市南山区" }, index);
  assert.equal(result.report["户籍"], "深圳户籍");
  assert.equal(result.report["医疗缴费档次"], "职工一档");
  assert.equal(result.report["户口具体地址"], "贵州省贵阳市南明区测试街道");
  assert.equal(result.report["户口所在地行政区划代码"], "520102.南明区");
  assert.ok(result.issues.some((value) => value.includes("地址冲突")));
});

test("户口地址缺省市时从同区县的户籍所在地补齐，保留详细地址", () => {
  const result = evaluateEmployee({ householdAddress: "南山区测试街道1号", birthplace: "广东省深圳市南山区" }, index);
  assert.equal(result.report["户口具体地址"], "广东省深圳市南山区测试街道1号");
});

test("户口地址仅到城市时从相同城市的户籍所在地补齐区县", () => {
  const result = matchAdminDivision({ householdAddress: "广东省深圳市", birthplace: "广东省深圳市南山区" }, index);
  assert.equal(result.value, "440305.南山区");
});

test("外省户口地址无法确定区县时，不使用冲突的深圳区县", () => {
  const result = matchAdminDivision({ householdAddress: "贵州省测试街道", birthplace: "广东省深圳市南山区" }, index);
  assert.equal(result.status, "manual");
  assert.equal(result.value, "");
});

test("户口地址只有唯一可识别区县时，不被冲突的户籍所在地带偏", () => {
  const result = evaluateEmployee({ householdAddress: "南山区测试街道1号", birthplace: "贵州省贵阳市南明区" }, index);
  assert.equal(result.report["户口所在地行政区划代码"], "440305.南山区");
  assert.equal(result.report["户口具体地址"], "广东省深圳市南山区测试街道1号");
});
