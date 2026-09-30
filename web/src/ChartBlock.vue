<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

// echarts 体积大（>1MB），动态导入拆为独立 chunk，仅在首次渲染图表时加载
let echartsPromise = null;
function loadEcharts() {
  if (!echartsPromise) echartsPromise = import("echarts");
  return echartsPromise;
}

const props = defineProps({ chart: Object, columns: Array, rows: Array });
const el = ref(null);
let inst = null;
let disposed = false;

function buildOption(echarts) {
  const { chart, columns, rows } = props;
  const xi = columns.indexOf(chart.x);
  const labels = rows.map((r) => String(r[xi]));
  if (chart.type === "pie") {
    const yi = columns.indexOf(chart.y[0]);
    return {
      tooltip: {},
      legend: {},
      series: [{
        type: "pie",
        radius: "62%",
        data: rows.map((r) => ({ name: String(r[xi]), value: r[yi] })),
      }],
    };
  }
  const series = chart.y.map((name) => {
    const yi = columns.indexOf(name);
    return {
      name,
      type: chart.type === "line" ? "line" : "bar",
      data: rows.map((r) => r[yi]),
    };
  });
  return {
    tooltip: {},
    legend: {},
    grid: { left: 40, right: 16, top: 30, bottom: 28 },
    xAxis: { type: "category", data: labels },
    yAxis: { type: "value" },
    series,
  };
}

async function render() {
  if (!el.value || !props.chart || props.chart.type === "table" || !props.rows?.length) return;
  const echarts = await loadEcharts();
  if (disposed || !el.value) return;
  if (!inst) inst = echarts.init(el.value);
  inst.setOption(buildOption(echarts), true);
  inst.resize();
}

onMounted(render);
onBeforeUnmount(() => {
  disposed = true;
  if (inst) { inst.dispose(); inst = null; }
});
watch(() => [props.chart, props.rows], render);
</script>

<template>
  <div class="chartwrap">
    <div ref="el" class="chart"></div>
    <p class="reason">图表建议：{{ chart?.reason }}</p>
  </div>
</template>

<style scoped>
.chartwrap { margin: 0 0 10px; }
.chart { width: 100%; height: 260px; }
.reason { margin: 4px 0 0; font-size: 12px; color: var(--muted); }
</style>
