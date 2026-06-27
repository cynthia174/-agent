import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "data";
await fs.mkdir(outputDir, { recursive: true });

let seed = 20260627;
function random() {
  seed = (seed * 1664525 + 1013904223) % 4294967296;
  return seed / 4294967296;
}
function pick(items) {
  return items[Math.floor(random() * items.length)];
}

const catalog = [
  ["星云降噪耳机", "数码家电", 699, 0.56],
  ["极光机械键盘", "数码家电", 429, 0.58],
  ["轻羽智能手表", "数码家电", 899, 0.61],
  ["云感记忆枕", "家居生活", 239, 0.45],
  ["原木收纳架", "家居生活", 329, 0.52],
  ["暖阳香薰机", "家居生活", 199, 0.47],
  ["城市通勤双肩包", "服饰箱包", 359, 0.48],
  ["轻氧防晒外套", "服饰箱包", 299, 0.43],
  ["复古帆布鞋", "服饰箱包", 269, 0.49],
  ["山野挂耳咖啡", "食品饮料", 89, 0.39],
  ["每日坚果礼盒", "食品饮料", 159, 0.62],
  ["低糖燕麦脆", "食品饮料", 69, 0.44],
];
const regions = ["华东", "华南", "华北", "西南", "华中"];
const regionWeight = {华东: 1.24, 华南: 1.12, 华北: 1.03, 西南: 0.88, 华中: 0.94};
const customers = ["新客户", "老客户", "企业客户"];
const headers = ["订单日期", "地区", "产品", "产品类别", "客户类型", "销售额", "成本", "折扣", "数量"];
const rows = [];

for (const year of [2024, 2025]) {
  for (let month = 0; month < 12; month++) {
    const season = [0.86, 0.78, 0.92, 0.98, 1.03, 1.08, 1.01, 1.06, 1.16, 1.12, 1.48, 1.42][month];
    for (let i = 0; i < 36; i++) {
      const [product, category, price, costRate] = pick(catalog);
      const region = pick(regions);
      const customer = pick(customers);
      const discount = pick([0, 0, 0.05, 0.1, 0.15, 0.2]);
      const baseQty = customer === "企业客户" ? 5 : 1;
      const quantity = Math.max(1, Math.round((baseQty + random() * 5) * season * regionWeight[region]));
      const sales = Math.round(price * quantity * (1 - discount) * 100) / 100;
      const cost = Math.round(price * quantity * costRate * 100) / 100;
      const day = 1 + Math.floor(random() * 28);
      rows.push([new Date(year, month, day), region, product, category, customer, sales, cost, discount, quantity]);
    }
  }
}

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("销售明细");
sheet.showGridLines = false;
sheet.getRangeByIndexes(0, 0, rows.length + 1, headers.length).values = [headers, ...rows];
sheet.getRange(`A1:I${rows.length + 1}`).format.font = { name: "Microsoft YaHei", size: 10 };
sheet.getRange("A1:I1").format = {
  fill: "#1D4ED8",
  font: { name: "Microsoft YaHei", size: 10, bold: true, color: "#FFFFFF" },
  rowHeight: 26,
};
sheet.getRange(`A2:A${rows.length + 1}`).format.numberFormat = "yyyy-mm-dd";
sheet.getRange(`F2:G${rows.length + 1}`).format.numberFormat = '¥#,##0.00';
sheet.getRange(`H2:H${rows.length + 1}`).format.numberFormat = "0%";
sheet.getRange(`I2:I${rows.length + 1}`).format.numberFormat = "0";
sheet.freezePanes.freezeRows(1);
sheet.tables.add(`A1:I${rows.length + 1}`, true, "SalesDataTable");
sheet.getRange(`A1:I${Math.min(rows.length + 1, 80)}`).format.autofitColumns();
sheet.getRange("A:A").format.columnWidth = 13;
sheet.getRange("C:C").format.columnWidth = 19;
sheet.getRange("D:E").format.columnWidth = 13;

const summary = workbook.worksheets.add("数据说明");
summary.showGridLines = false;
summary.getRange("A1:D1").merge();
summary.getRange("A1").values = [["AI 销售分析演示数据"]];
summary.getRange("A1:D1").format = {fill:"#1D4ED8", font:{name:"Microsoft YaHei", size:16, bold:true, color:"#FFFFFF"}, rowHeight:34};
summary.getRange("A3:B8").values = [
  ["项目", "内容"],
  ["数据用途", "AI 数据分析产品演示"],
  ["订单数量", rows.length],
  ["日期范围", "2024-01-01 至 2025-12-31"],
  ["产品数量", catalog.length],
  ["说明", "全部数据为模拟生成，不包含真实客户信息"],
];
summary.getRange("A3:B3").format = {fill:"#DBEAFE", font:{bold:true, color:"#1E3A8A"}};
summary.getRange("A3:B8").format.font = {name:"Microsoft YaHei", size:11};
summary.getRange("A:A").format.columnWidth = 18;
summary.getRange("B:B").format.columnWidth = 48;

const check = await workbook.inspect({
  kind: "table",
  range: "数据说明!A1:B8",
  include: "values,formulas",
  tableMaxRows: 10,
  tableMaxCols: 4,
});
console.log(check.ndjson);
const preview = await workbook.render({
  sheetName: "数据说明",
  range: "A1:D8",
  scale: 2,
  format: "png",
});
await fs.writeFile(`${outputDir}/数据表预览.png`, new Uint8Array(await preview.arrayBuffer()));

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(`${outputDir}/电商销售数据.xlsx`);

function csvEscape(v) {
  const text = v instanceof Date
    ? `${v.getFullYear()}-${String(v.getMonth()+1).padStart(2,"0")}-${String(v.getDate()).padStart(2,"0")}`
    : String(v);
  return `"${text.replaceAll('"', '""')}"`;
}
const csv = "\uFEFF" + [headers, ...rows].map(row => row.map(csvEscape).join(",")).join("\n");
await fs.writeFile(`${outputDir}/电商销售数据.csv`, csv, "utf8");
console.log(JSON.stringify({rows: rows.length, xlsx: `${outputDir}/电商销售数据.xlsx`, csv: `${outputDir}/电商销售数据.csv`}));
