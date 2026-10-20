const $ = (id) => document.getElementById(id);
const number = (value) => new Intl.NumberFormat('vi-VN').format(Number(value || 0));
const decimal = (value, digits = 1) => new Intl.NumberFormat('vi-VN', {minimumFractionDigits: digits, maximumFractionDigits: digits}).format(Number(value));
const percent = (part, total) => total ? `${decimal(100 * Number(part) / Number(total), 2)}%` : '—';
const compactValue = (value) => {
  const n = Number(value || 0);
  return n >= 1e6 ? `R$ ${decimal(n / 1e6, 2)} triệu` : `R$ ${number(Math.round(n))}`;
};
const monthLabel = (key) => `Tháng ${String(key).slice(4)}/${String(key).slice(0, 4)}`;
const pageInfo = {
  overview: ['DASHBOARD / TỔNG QUAN', 'Tổng quan Olist', 'Quy mô đơn hàng, giá trị sản phẩm và chất lượng phục vụ.'],
  delivery: ['DASHBOARD / CHẨN ĐOÁN', 'Chẩn đoán giao trễ', 'So sánh các chặng giao hàng và tìm nhóm có tỷ lệ trễ nổi bật.'],
  products: ['DASHBOARD / SẢN PHẨM & NGƯỜI BÁN', 'Sản phẩm và người bán', 'Cơ cấu danh mục, mức độ tập trung và vị trí người bán.'],
  customers: ['DASHBOARD / KHÁCH HÀNG & ĐÁNH GIÁ', 'Khách hàng và trải nghiệm', 'Hành vi mua tiếp theo, đánh giá và mối liên hệ với giao hàng.'],
  predictions: ['DASHBOARD / ƯU TIÊN GIAO HÀNG', 'Ưu tiên xử lý giao hàng', 'Nhìn nhanh khối lượng cần chú ý, khu vực tập trung và đơn nên xem trước.'],
};
const dimensionNotes = {
  customer_state: 'Vị trí của khách hàng trong đơn; tối đa 27 bang.',
  order_status: 'Trạng thái đơn tại thời điểm dữ liệu Olist được trích xuất.',
  order_size_band: 'Số dòng sản phẩm trong một đơn, theo nhóm 0 / 1 / 2 / 3 trở lên.',
  promise_window_band: 'Số ngày từ lúc đặt đến ngày giao dự kiến; là nhóm mô tả.',
  purchase_weekday: 'Ngày trong tuần khi khách đặt đơn; 0 = Chủ nhật.',
};
const weekdays = ['Chủ nhật', 'Thứ hai', 'Thứ ba', 'Thứ tư', 'Thứ năm', 'Thứ sáu', 'Thứ bảy'];
let defaults, dashboard, predictionData, predictionAction = 'all', sortKey = 'orders', sortDescending = true, refreshRequest = 0;

function showNotice(message, error = false) {
  const node = $('notice');
  node.textContent = message;
  node.classList.toggle('show', Boolean(message));
  node.classList.toggle('error', error);
}

async function json(url) {
  const response = await fetch(url, {cache: 'no-store'});
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Không đọc được dữ liệu');
  return body;
}

function svgElement(tag, attributes = {}) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  return node;
}

function selectMonth(month) {
  if (!defaults?.months.map(String).includes(String(month)) || $('month').value === String(month)) return;
  $('month').value = String(month);
  refresh();
}

function addMonthTargets(svg, months, centers, step, top, bottom, details = []) {
  months.forEach((month, index) => {
    const target=svgElement('rect',{x:centers[index]-step/2,y:top,width:step,height:bottom-top,
      fill:'transparent',class:'chart-hit',role:'button',tabindex:0,'aria-label':`Xem ${monthLabel(month)}`});
    const title=svgElement('title');title.textContent=`${monthLabel(month)}${details[index] ? `: ${details[index]}` : ''} · Bấm để xem chi tiết`;target.append(title);
    target.addEventListener('click',()=>selectMonth(month));
    target.addEventListener('keydown',(event)=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectMonth(month);}});
    svg.append(target);
  });
}

function renderTrend(trend) {
  const holder = $('trendChart');
  holder.replaceChildren();
  if (!trend.length) { holder.textContent = 'Không có dữ liệu trong kỳ lọc.'; return; }
  const metric=$('trendMetric').value;
  const valueOf=(row)=>{
    if (metric==='aov') return row.orders ? Number(row.ordered_item_value)/Number(row.orders) : null;
    if (metric==='late_rate') return row.eligible_orders ? Number(row.late_orders)/Number(row.eligible_orders) : null;
    if (metric==='review_score') return row.reviewed_orders ? Number(row.review_score_sum)/Number(row.reviewed_orders) : null;
    return Number(row[metric]);
  };
  const format=(value)=>{
    if (value===null) return '—';
    if (metric==='ordered_item_value') return compactValue(value);
    if (metric==='aov') return `R$ ${decimal(value,2)}`;
    if (metric==='late_rate') return `${decimal(value*100,1)}%`;
    if (metric==='review_score') return `${decimal(value,2)}/5`;
    return number(Math.round(value));
  };
  const values=trend.map(valueOf);
  const available=values.filter((value)=>value!==null && Number.isFinite(value));
  if (!available.length) { holder.textContent='Không có dữ liệu cho chỉ số này trong kỳ lọc.'; return; }
  const svg = svgElement('svg', {viewBox:'0 0 900 280', preserveAspectRatio:'none', role:'img'});
  const left = 72, right = 842, top = 24, bottom = 230;
  const width = right - left, height = bottom - top;
  const max=Math.max(...available,metric==='review_score'?5:0.01)*(metric==='review_score'?1:1.15);
  const min=metric==='review_score'?1:0;
  const y=(value)=>bottom-(value-min)/(max-min)*height;
  for (let i = 0; i < 4; i++) {
    const y = top + i * height / 3;
    svg.append(svgElement('line', {x1:left, y1:y, x2:right, y2:y, stroke:'#edf1ef'}));
    const label = svgElement('text', {x:1, y:y+4, fill:'#98a6a9', 'font-size':10});
    label.textContent = format(max-(max-min)*i/3); svg.append(label);
  }
  const step = width / trend.length;
  const centers = trend.map((_, i) => left + step * (i + .5));
  const bars=metric==='orders'||metric==='ordered_item_value';
  trend.forEach((row, i) => {
    if (bars && values[i]!==null) {
      const barHeight=bottom-y(values[i]);
      const bar=svgElement('rect',{x:centers[i]-Math.min(step*.58,34)/2,y:bottom-barHeight,
        width:Math.min(step*.58,34),height:barHeight,rx:3,fill:i===trend.length-1?'#2a9b89':'#9bd1c5'});
      const title=svgElement('title');title.textContent=`${monthLabel(row.month_key)}: ${format(values[i])}`;
      bar.append(title);svg.append(bar);
    }
    const label = svgElement('text', {x:centers[i], y:256, 'text-anchor':'middle', fill:'#98a6a9', 'font-size':10});
    label.textContent = `${String(row.month_key).slice(4)}/${String(row.month_key).slice(2,4)}`; svg.append(label);
  });
  if (!bars) {
    for (let i=1;i<values.length;i++) {
      if (values[i-1]===null||values[i]===null) continue;
      svg.append(svgElement('line',{x1:centers[i-1],y1:y(values[i-1]),x2:centers[i],y2:y(values[i]),stroke:'#d87e54','stroke-width':3}));
    }
    values.forEach((value,i)=>{
      if (value===null) return;
      const dot=svgElement('circle',{cx:centers[i],cy:y(value),r:4,fill:'#d87e54',stroke:'#fff','stroke-width':1.5});
      const title=svgElement('title');title.textContent=`${monthLabel(trend[i].month_key)}: ${format(value)}`;
      dot.append(title);svg.append(dot);
    });
  }
  addMonthTargets(svg,trend.map((row)=>row.month_key),centers,step,top,256,values.map(format));
  holder.append(svg);
}

function renderStateSummary(states) {
  const holder = $('overviewStateRows'); holder.replaceChildren();
  const selected = states.filter((row) => Number(row.eligible_orders) > 0)
    .sort((a,b) => Number(b.eligible_orders) - Number(a.eligible_orders))
    .slice(0,5);
  if (!selected.length) {
    const empty = document.createElement('p'); empty.className='empty';
    empty.textContent='Không có đơn giao đủ điều kiện trong nhóm lọc này.'; holder.append(empty); return;
  }
  const maxRate = Math.max(...selected.map((row) => Number(row.late_orders)/Number(row.eligible_orders)),0.01);
  selected.forEach((row) => {
    const currentRate=Number(row.late_orders)/Number(row.eligible_orders);
    const previousRate=row.previous_eligible_orders ? Number(row.previous_late_orders)/Number(row.previous_eligible_orders) : null;
    const delta=previousRate === null ? null : (currentRate-previousRate)*100;
    const item=document.createElement('button'); item.type='button'; item.className='state-summary-row state-drilldown';
    item.title=`Xem chi tiết bang ${row.label}`;
    item.addEventListener('click',()=>{ $('state').value=row.label; location.hash='delivery'; refresh(); });
    const identity=document.createElement('div'); identity.className='state-identity';
    const name=document.createElement('strong'); name.textContent=row.label;
    const volume=document.createElement('small'); volume.textContent=`${number(row.eligible_orders)} đơn đủ điều kiện`;
    identity.append(name,volume);
    const result=document.createElement('div'); result.className='state-result';
    const values=document.createElement('div'); values.className='state-values';
    const rate=document.createElement('strong'); rate.textContent=percent(row.late_orders,row.eligible_orders);
    const prior=document.createElement('span'); prior.textContent=`Trước: ${percent(row.previous_late_orders,row.previous_eligible_orders)}`;
    const change=document.createElement('span'); change.textContent=delta === null ? '—' : `${signed(delta,' điểm %',2)} MoM`;
    change.className=delta === null ? '' : delta > 0 ? 'negative' : delta < 0 ? 'positive' : '';
    values.append(rate,prior,change);
    const track=document.createElement('div'); track.className='state-rate-track';
    const fill=document.createElement('span'); fill.style.width=`${100*currentRate/maxRate}%`;
    track.append(fill); result.append(values,track); item.append(identity,result); holder.append(item);
  });
}

function signed(value, suffix, digits = 1) {
  if (value === null || value === undefined) return '—';
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return `${sign}${decimal(Math.abs(value), digits)}${suffix}`;
}

function mom(id, value, suffix, digits) {
  const node = $(id);
  node.textContent = value === null ? 'Chưa có số liệu so sánh' : `${signed(value, suffix, digits)} so với tháng trước`;
  const up = value !== null && value > 0;
  const down = value !== null && value < 0;
  node.classList.toggle('positive', up);
  node.classList.toggle('negative', down);
  node.closest('.kpi-card').classList.toggle('trend-up', up);
  node.closest('.kpi-card').classList.toggle('trend-down', down);
}

function renderKpis(comparison) {
  const {current, previous, mom: changes} = comparison;
  $('ordersValue').textContent = number(current.orders);
  $('itemValue').textContent = compactValue(current.ordered_item_value);
  $('aovValue').textContent = comparison.current_aov === null ? '—' : `R$ ${decimal(comparison.current_aov, 2)}`;
  $('lateOrdersValue').textContent = number(current.late_orders);
  $('lateRateValue').textContent = comparison.current_late_rate === null ? '—' : `${decimal(comparison.current_late_rate * 100, 2)}%`;
  $('reviewValue').textContent = comparison.current_review_score === null ? '—' : `${decimal(comparison.current_review_score, 2)}/5`;
  mom('ordersMom', changes.orders_percent, '%', 1);
  mom('itemMom', changes.ordered_item_value_percent, '%', 1);
  mom('aovMom', changes.aov_percent, '%', 1);
  mom('lateOrdersMom', changes.late_orders_percent, '%', 1);
  mom('lateRateMom', changes.late_rate_percentage_points, ' điểm %', 2);
  mom('reviewMom', changes.review_score_difference, ' điểm', 2);
  $('ordersPrevious').textContent = `Tháng trước: ${number(previous.orders)} đơn`;
  $('itemPrevious').textContent = `Tháng trước: ${compactValue(previous.ordered_item_value)}`;
  $('aovPrevious').textContent = `Tháng trước: ${comparison.previous_aov === null ? '—' : 'R$ ' + decimal(comparison.previous_aov, 2)}`;
  $('lateOrdersPrevious').textContent = `Tháng trước: ${number(previous.late_orders)} đơn trễ`;
  $('lateRatePrevious').textContent = `Tháng trước: ${comparison.previous_late_rate === null ? '—' : decimal(comparison.previous_late_rate * 100, 2) + '%'}`;
  $('lateRateDenominator').textContent = `Tính trên ${number(current.eligible_orders)} đơn đã giao đủ điều kiện`;
  $('reviewPrevious').textContent = `Tháng trước: ${comparison.previous_review_score === null ? '—' : decimal(comparison.previous_review_score, 2) + '/5'}`;
  $('reviewDenominator').textContent = `${number(current.reviewed_orders)} đơn có đánh giá`;
  $('comparisonLabel').textContent = `${monthLabel(comparison.month)} / ${monthLabel(comparison.previous_month)}`;
  $('partialNote').hidden = currentPage() === 'predictions' || !comparison.month_is_partial;
  $('partialNote').textContent = 'Tháng được chọn chưa đủ dữ liệu. Các so sánh với tháng trước dùng toàn bộ tháng trước nên chỉ mang tính tham khảo.';
}

function groupName(dimension, label) {
  if (dimension === 'purchase_weekday') return weekdays[Number(label)] || String(label);
  if (label === '<missing>') return 'Thiếu dữ liệu';
  if (label === 'unknown') return 'Không rõ';
  if (label === 'invalid') return 'Không hợp lệ';
  return String(label).replace('items', 'dòng hàng').replace('days', 'ngày');
}

function renderStages(groups) {
  const byGroup=Object.fromEntries(groups.map((row)=>[row.delivery_group,row]));
  const all=byGroup.all;
  const summary=$('stageSummary'), holder=$('stageRows');
  summary.replaceChildren(); holder.replaceChildren();
  $('stageCohort').textContent=all ? `${number(all.eligible_orders)} đơn giao đủ điều kiện` : 'Không có đơn đủ điều kiện';
  if (!all || !all.eligible_orders) {
    holder.textContent='Không có đơn giao đủ điều kiện trong nhóm lọc này.';
    return;
  }
  const cards=[
    ['Giao thực tế TB',all.actual_days,'ngày',`${number(all.eligible_orders)} đơn có nhãn`],
    ['Hẹn giao TB',all.promised_days,'ngày',`${number(all.eligible_orders)} đơn có nhãn`],
    ['Số ngày trễ TB',all.late_delay_days,'ngày',`${number(byGroup.late?.eligible_orders || 0)} đơn giao trễ`],
  ];
  cards.forEach(([label,value,unit,detail])=>{
    const card=document.createElement('div'); card.className='stage-summary-card';
    const name=document.createElement('span'); name.textContent=label;
    const strong=document.createElement('strong'); strong.textContent=value === null ? '—' : `${decimal(value,1)} ${unit}`;
    const small=document.createElement('small'); small.textContent=detail;
    card.append(name,strong,small); summary.append(card);
  });
  const stages=[
    ['Duyệt đơn','approval_days','approval_count'],
    ['Chuẩn bị hàng','preparation_days','preparation_count'],
    ['Vận chuyển','transit_days','transit_count'],
  ];
  const max=Math.max(...stages.flatMap(([,key])=>[Number(byGroup.late?.[key] || 0),Number(byGroup.on_time?.[key] || 0)]),1);
  stages.forEach(([label,key,countKey])=>{
    const row=document.createElement('div'); row.className='stage-row';
    const title=document.createElement('strong'); title.textContent=label;
    const tracks=document.createElement('div'); tracks.className='stage-tracks';
    [['late','Đơn trễ'],['on_time','Đúng hạn']].forEach(([groupName,labelText])=>{
      const group=byGroup[groupName], value=group?.[key], count=group?.[countKey] || 0;
      const line=document.createElement('div'); line.className='stage-track-row';
      const track=document.createElement('div'); track.className='stage-track';
      const bar=document.createElement('span'); bar.className=groupName;
      bar.style.width=`${value === null || value === undefined ? 0 : 100*Number(value)/max}%`;
      track.append(bar);
      const valueText=document.createElement('span'); valueText.textContent=`${labelText}: ${value === null || value === undefined ? '—' : decimal(value,2)+' ngày'} · n=${number(count)}`;
      line.append(track,valueText); tracks.append(line);
    });
    row.append(title,tracks); holder.append(row);
  });
}

function renderDiagnosticHighlights(data) {
  const holder=$('diagnosticHighlights'); holder.replaceChildren();
  const stageByGroup=Object.fromEntries(data.delivery_stages.map((row)=>[row.delivery_group,row]));
  const all=stageByGroup.all, late=stageByGroup.late, onTime=stageByGroup.on_time;
  if (!all?.eligible_orders) {
    $('insightThreshold').textContent='';
    const empty=document.createElement('div'); empty.className='panel empty';
    empty.textContent='Không có đơn giao đủ điều kiện trong nhóm lọc này.'; holder.append(empty); return;
  }
  const add=(label,value,detail)=>{
    const card=document.createElement('article'); card.className='panel insight-card';
    const title=document.createElement('span'); title.textContent=label;
    const strong=document.createElement('strong'); strong.textContent=value;
    const small=document.createElement('p'); small.textContent=detail;
    card.append(title,strong,small);holder.append(card);
  };
  const stages=[
    ['Duyệt đơn','approval_days','approval_count'],
    ['Chuẩn bị hàng','preparation_days','preparation_count'],
    ['Vận chuyển','transit_days','transit_count'],
  ].filter(([,key,count])=>late?.[key] != null && onTime?.[key] != null && late[count]>=20 && onTime[count]>=20)
    .map(([label,key,count])=>({label,late:Number(late[key]),onTime:Number(onTime[key]),lateN:late[count],onTimeN:onTime[count]}))
    .sort((a,b)=>Math.abs(b.late-b.onTime)-Math.abs(a.late-a.onTime));
  if (stages.length) {
    const stage=stages[0];
    add('Chặng khác biệt lớn nhất',signed(stage.late-stage.onTime,' ngày',2),
      `${stage.label}: nhóm trễ ${decimal(stage.late,2)} ngày (n=${number(stage.lateN)}), nhóm đúng hạn ${decimal(stage.onTime,2)} ngày (n=${number(stage.onTimeN)}).`);
  }
  const minimum=Math.max(20,Math.ceil(Number(all.eligible_orders)*.01));
  $('insightThreshold').textContent=`Chỉ hiển thị nhóm có từ ${number(minimum)} đơn.`;
  const promises=data.breakdowns.promise_window_band
    .filter((row)=>Number(row.eligible_orders)>=minimum)
    .sort((a,b)=>Number(b.late_orders)/Number(b.eligible_orders)-Number(a.late_orders)/Number(a.eligible_orders));
  if (promises.length) {
    const row=promises[0], rate=Number(row.late_orders)/Number(row.eligible_orders);
    const gap=(rate-data.comparison.current_late_rate)*100;
    add('Khoảng hẹn có tỷ lệ trễ cao nhất',percent(row.late_orders,row.eligible_orders),
      `${groupName('promise_window_band',row.label)}: ${number(row.late_orders)}/${number(row.eligible_orders)} đơn; ${signed(gap,' điểm %',2)} so với toàn nhóm lọc.`);
  }
  const cells=data.delivery_matrix.customer_state
    .filter((row)=>Number(row.eligible_orders)>=minimum)
    .sort((a,b)=>Number(b.late_orders)-Number(a.late_orders));
  if (cells.length) {
    const cell=cells[0];
    add('Ô có nhiều đơn trễ nhất',`${number(cell.late_orders)} đơn`,
      `${cell.label} × ${groupName('promise_window_band',cell.promise_window_band)}: tỷ lệ ${percent(cell.late_orders,cell.eligible_orders)} trên ${number(cell.eligible_orders)} đơn đủ điều kiện.`);
  }
}

function renderMatrix() {
  if (!dashboard) return;
  const dimension=$('matrixDimension').value;
  const data=dashboard.delivery_matrix[dimension].filter((row)=>Number(row.eligible_orders)>0);
  const holder=$('matrixHolder'); holder.replaceChildren();
  const bands=['<14 days','14-29 days','30+ days','unknown','invalid'].filter((band)=>data.some((row)=>row.promise_window_band===band));
  const grouped=new Map();
  data.forEach((row)=>{
    if (!grouped.has(row.label)) grouped.set(row.label,{label:row.label,eligible:0,late:0,cells:new Map()});
    const item=grouped.get(row.label);
    item.eligible+=Number(row.eligible_orders); item.late+=Number(row.late_orders);
    item.cells.set(row.promise_window_band,row);
  });
  const entries=[...grouped.values()].sort((a,b)=>b.eligible-a.eligible);
  const shown=dimension==='customer_state' ? entries.slice(0,10) : entries;
  $('matrixDescription').textContent=dimension==='customer_state'
    ? '10 bang có nhiều đơn đủ điều kiện nhất × khoảng hẹn giao'
    : `${$('matrixDimension').selectedOptions[0].textContent} × khoảng hẹn giao`;
  if (!shown.length) {holder.textContent='Không có đơn giao đủ điều kiện trong nhóm lọc này.';return;}
  const table=document.createElement('table'); table.className='matrix-table';
  const thead=document.createElement('thead'), trHead=document.createElement('tr');
  ['Nhóm',...bands.map((band)=>groupName('promise_window_band',band)),'Tất cả'].forEach((label)=>{
    const th=document.createElement('th'); th.textContent=label; trHead.append(th);
  });
  thead.append(trHead); table.append(thead);
  const tbody=document.createElement('tbody');
  shown.forEach((item)=>{
    const tr=document.createElement('tr');
    const name=document.createElement('td');
    if (dimension==='customer_state' && item.label !== 'unknown') {
      const drill=document.createElement('button');drill.type='button';drill.className='table-drill';
      drill.textContent=groupName(dimension,item.label);drill.title=`Lọc bang ${item.label}`;
      drill.addEventListener('click',()=>{$('state').value=item.label;refresh();});name.append(drill);
    } else name.textContent=groupName(dimension,item.label);
    tr.append(name);
    bands.forEach((band)=>{
      const td=document.createElement('td'), cell=item.cells.get(band);
      const n=Number(cell?.eligible_orders || 0), late=Number(cell?.late_orders || 0);
      td.textContent=n ? `${percent(late,n)} · n=${number(n)}` : '—';
      td.className=n<20 ? 'heat-low-sample' : 'heat-cell';
      if (n>=20) td.style.backgroundColor=`rgba(216,126,84,${Math.min(.68,.07+late/n*2.5)})`;
      td.title=n<20 && n ? 'Mẫu nhỏ: chưa tô màu' : '';
      tr.append(td);
    });
    const total=document.createElement('td'); total.textContent=`${percent(item.late,item.eligible)} · n=${number(item.eligible)}`; total.className='matrix-total';
    tr.append(total);tbody.append(tr);
  });
  table.append(tbody);holder.append(table);
}

function renderBreakdown() {
  if (!dashboard) return;
  const dimension = $('dimension').value;
  $('dimensionDescription').textContent = dimensionNotes[dimension];
  const rows = dashboard.breakdowns[dimension].map((row) => ({...row,
    late_rate: row.eligible_orders ? Number(row.late_orders)/Number(row.eligible_orders) : null,
    delivery_days: row.eligible_orders ? Number(row.delivery_days_sum)/Number(row.eligible_orders) : null,
    late_gap: row.eligible_orders && dashboard.comparison.current_late_rate !== null
      ? (Number(row.late_orders)/Number(row.eligible_orders)-dashboard.comparison.current_late_rate)*100 : null,
  }));
  rows.sort((a,b) => {
    if (sortKey === 'label') return groupName(dimension,a.label).localeCompare(groupName(dimension,b.label),'vi') * (sortDescending ? -1 : 1);
    const av = a[sortKey] === null ? -Infinity : Number(a[sortKey]);
    const bv = b[sortKey] === null ? -Infinity : Number(b[sortKey]);
    return (av - bv) * (sortDescending ? -1 : 1);
  });
  const body = $('breakdownRows'); body.replaceChildren();
  if (!rows.length) { const tr=document.createElement('tr'); const td=document.createElement('td'); td.colSpan=7; td.textContent='Không có dữ liệu.'; tr.append(td); body.append(tr); return; }
  const maxOrders = Math.max(...rows.map((row) => Number(row.orders)),1);
  rows.forEach((row) => {
    const tr=document.createElement('tr');
    const name=document.createElement('td'); name.textContent=groupName(dimension,row.label);
    const orders=document.createElement('td');
    const bar=document.createElement('span'); bar.className='mini-bar'; bar.style.width=`${Math.max(3,60*Number(row.orders)/maxOrders)}px`;
    orders.append(bar,document.createTextNode(number(row.orders)));
    const eligible=document.createElement('td'); eligible.textContent=number(row.eligible_orders);
    const rate=document.createElement('td'); rate.textContent=percent(row.late_orders,row.eligible_orders);
    const gap=document.createElement('td'); gap.textContent=row.late_gap === null ? '—' : signed(row.late_gap,' điểm %',2);
    gap.className=row.late_gap === null ? '' : row.late_gap>0 ? 'negative' : row.late_gap<0 ? 'positive' : '';
    const days=document.createElement('td'); days.textContent=row.delivery_days === null ? '—' : `${decimal(row.delivery_days,1)} ngày`;
    const value=document.createElement('td'); value.textContent=compactValue(row.ordered_item_value);
    tr.append(name,orders,eligible,rate,gap,days,value); body.append(tr);
  });
}

function productBar(holder, label, value, total, detail, onClick) {
  const row = document.createElement(onClick ? 'button' : 'div');
  row.className = 'product-bar-row';
  if (onClick) { row.type = 'button'; row.addEventListener('click', onClick); }
  const heading = document.createElement('div'); heading.className = 'product-bar-heading';
  const name = document.createElement('strong'); name.textContent = label;
  const amount = document.createElement('span'); amount.textContent = `${compactValue(value)} · ${percent(value,total)}`;
  heading.append(name, amount);
  const track = document.createElement('div'); track.className = 'product-bar-track';
  const fill = document.createElement('span'); fill.style.width = `${Math.min(100, 100 * Number(value) / Math.max(Number(total), 1))}%`;
  track.append(fill);
  const note = document.createElement('small'); note.textContent = detail;
  row.append(heading,track,note); holder.append(row);
}

function renderProductSummary(data) {
  const summary = data.product_summary, comparison = data.comparison;
  $('productItemValue').textContent = compactValue(comparison.current.ordered_item_value);
  $('productItemLines').textContent = number(summary.item_lines);
  $('productCategoryCount').textContent = number(summary.active_categories);
  $('productSellerCount').textContent = number(summary.active_sellers);
  mom('productItemValueMom', comparison.mom.ordered_item_value_percent, '%', 1);
  const relative = (now, before) => before ? (Number(now)/Number(before)-1)*100 : null;
  mom('productItemLinesMom', relative(summary.item_lines,summary.previous_item_lines), '%', 1);
  mom('productCategoryMom', relative(summary.active_categories,summary.previous_active_categories), '%', 1);
  mom('productSellerMom', relative(summary.active_sellers,summary.previous_active_sellers), '%', 1);
  $('productItemLinesPrevious').textContent = `Tháng trước: ${number(summary.previous_item_lines)} dòng`;
  $('productCategoryPrevious').textContent = `Tháng trước: ${number(summary.previous_active_categories)} danh mục`;
  $('productSellerPrevious').textContent = `Tháng trước: ${number(summary.previous_active_sellers)} người bán`;
}

function renderCategoryTrend() {
  if (!dashboard) return;
  const holder = $('categoryTrendChart'); holder.replaceChildren();
  const selected = $('categoryTrendSelect').value;
  const months = dashboard.trend.map((row) => row.month_key);
  if (!selected || !months.length) { holder.textContent='Không có dữ liệu xu hướng.'; return; }
  const valuesByMonth = new Map(dashboard.category_trend.filter((row) => row.category_name === selected)
    .map((row) => [row.month_key, Number(row.ordered_item_value)]));
  const values = months.map((month) => valuesByMonth.get(month) || 0);
  const svg = svgElement('svg', {viewBox:'0 0 720 260',preserveAspectRatio:'none',role:'img'});
  const left=75,right=686,top=24,bottom=210,width=right-left,height=bottom-top;
  const max=Math.max(...values,1)*1.1;
  for (let i=0;i<4;i++) {
    const yy=top+i*height/3;
    svg.append(svgElement('line',{x1:left,y1:yy,x2:right,y2:yy,stroke:'#edf1ef'}));
    const label=svgElement('text',{x:2,y:yy+4,fill:'#98a6a9','font-size':10});
    label.textContent=compactValue(max*(1-i/3)); svg.append(label);
  }
  const x=(i)=>left+(months.length===1?width/2:i*width/(months.length-1));
  const y=(value)=>bottom-value/max*height;
  values.forEach((value,i)=>{
    if (i) svg.append(svgElement('line',{x1:x(i-1),y1:y(values[i-1]),x2:x(i),y2:y(value),stroke:'#2a9b89','stroke-width':3}));
    const dot=svgElement('circle',{cx:x(i),cy:y(value),r:4,fill:'#2a9b89'});
    const tip=svgElement('title');tip.textContent=`${monthLabel(months[i])}: ${compactValue(value)}`;dot.append(tip);svg.append(dot);
    const label=svgElement('text',{x:x(i),y:239,'text-anchor':'middle',fill:'#98a6a9','font-size':10});
    label.textContent=`${String(months[i]).slice(4)}/${String(months[i]).slice(2,4)}`;svg.append(label);
  });
  addMonthTargets(svg,months,months.map((_,i)=>x(i)),width/Math.max(months.length-1,1),top,239,values.map(compactValue));
  holder.append(svg);
}

function renderCategoryTable() {
  if (!dashboard) return;
  const search=$('categorySearch').value.trim().toLocaleLowerCase();
  const rows=dashboard.categories.filter((row)=>String(row.category_name).replaceAll('_',' ').toLocaleLowerCase().includes(search));
  $('categoryTableCount').textContent=`${number(rows.length)} / ${number(dashboard.categories.length)} danh mục đang hiển thị`;
  const holder=$('categoryTableRows');holder.replaceChildren();
  const total=dashboard.comparison.current.ordered_item_value;
  if (!rows.length) { const row=document.createElement('tr'); const cell=document.createElement('td');cell.colSpan=6;cell.textContent='Không tìm thấy danh mục.';row.append(cell);holder.append(row);return; }
  rows.forEach((category)=>{
    const tr=document.createElement('tr');
    const previous=Number(category.previous_item_value);
    const delta=previous ? (Number(category.ordered_item_value)/previous-1)*100 : null;
    const values=[String(category.category_name).replaceAll('_',' '),number(category.item_lines),number(category.orders_with_category),compactValue(category.ordered_item_value),percent(category.ordered_item_value,total),signed(delta,'%',1)];
    values.forEach((value,i)=>{const cell=document.createElement('td');cell.textContent=value;if(i===5&&delta!==null)cell.className=delta<0?'negative':'positive';tr.append(cell);});
    holder.append(tr);
  });
}

function renderCategories(categories) {
  const holder=$('categoryRows');holder.replaceChildren();
  const total=Number(dashboard.comparison.current.ordered_item_value);
  if (!categories.length || !total) {holder.textContent='Không có dữ liệu trong kỳ lọc.';return;}
  const selector=$('categoryTrendSelect'), selected=selector.value;selector.replaceChildren();
  categories.forEach((row)=>{const option=document.createElement('option');option.value=row.category_name;option.textContent=String(row.category_name).replaceAll('_',' ');selector.append(option);});
  selector.value=categories.some((row)=>row.category_name===selected)?selected:categories[0].category_name;
  let cumulative=0, thresholdCount=0;
  categories.forEach((row,index)=>{if (cumulative < total*.8) {cumulative+=Number(row.ordered_item_value);thresholdCount=index+1;}});
  $('categoryConcentration').textContent=`${number(thresholdCount)}/${number(categories.length)} danh mục tạo ít nhất 80% giá trị đặt`;
  categories.slice(0,8).forEach((row,index)=>productBar(holder,
    `${String(index+1).padStart(2,'0')} · ${String(row.category_name).replaceAll('_',' ')}`,
    row.ordered_item_value,total,`${number(row.item_lines)} dòng hàng`,()=>{selector.value=row.category_name;renderCategoryTrend();}));
  const rest=total-categories.slice(0,8).reduce((sum,row)=>sum+Number(row.ordered_item_value),0);
  if (rest>0) productBar(holder,'Các danh mục còn lại',rest,total,`${number(categories.length-8)} danh mục`);
  renderCategoryTable();renderCategoryTrend();
}

function renderSellers(data) {
  const total=Number(data.comparison.current.ordered_item_value);
  $('sellerConcentration').textContent=`Top 10 người bán: ${percent(data.sellers.slice(0,10).reduce((sum,row)=>sum+Number(row.ordered_item_value),0),total)} giá trị đặt`;
  const holders=[[$('sellerRows'),data.sellers.slice(0,10),'seller'],[$('sellerStateRows'),data.seller_states,'state']];
  holders.forEach(([holder,rows,type])=>{
    holder.replaceChildren();
    if (!rows.length) {holder.textContent='Không có dữ liệu trong kỳ lọc.';return;}
    rows.forEach((row,index)=>{
      const label=type==='seller'?`${String(index+1).padStart(2,'0')} · ${row.seller_city}, ${row.seller_state}`:`${row.seller_state}`;
      const detail=type==='seller'?`ID ${row.seller_id.slice(0,10)}… · ${number(row.item_lines)} dòng · ${number(row.orders_with_seller)} đơn chứa người bán`:`${number(row.active_sellers)} người bán · ${number(row.item_lines)} dòng hàng`;
      productBar(holder,label,row.ordered_item_value,total,detail);
    });
  });
}

function renderCustomerKpis(customer) {
  const {current, previous, current_rates: rates, previous_rates: prior, mom: changes}=customer.comparison;
  $('buyerValue').textContent=number(current.buyers);
  $('returningValue').textContent=number(current.previously_observed_buyers);
  $('returningShareValue').textContent=rates.returning_buyer_share===null?'—':`${decimal(rates.returning_buyer_share*100,2)}%`;
  $('reviewCoverageValue').textContent=rates.review_coverage===null?'—':`${decimal(rates.review_coverage*100,2)}%`;
  $('customerReviewValue').textContent=rates.review_score===null?'—':`${decimal(rates.review_score,2)}/5`;
  $('lowReviewValue').textContent=rates.low_review_share===null?'—':`${decimal(rates.low_review_share*100,2)}%`;
  mom('buyerMom',changes.buyers_percent,'%',1);
  mom('returningMom',changes.previously_observed_buyers_percent,'%',1);
  mom('returningShareMom',changes.returning_buyer_share_difference,' điểm %',2);
  mom('reviewCoverageMom',changes.review_coverage_difference,' điểm %',2);
  mom('customerReviewMom',changes.review_score_difference,' điểm',2);
  mom('lowReviewMom',changes.low_review_share_difference,' điểm %',2);
  $('buyerPrevious').textContent=`Tháng trước: ${number(previous.buyers)} người`;
  $('returningPrevious').textContent=`Tháng trước: ${number(previous.previously_observed_buyers)} người`;
  $('returningShareDenominator').textContent=`${number(current.previously_observed_buyers)} / ${number(current.buyers)} người mua`;
  $('reviewCoverageDenominator').textContent=`${number(current.delivered_reviewed_orders)} / ${number(current.delivered_orders)} đơn trạng thái đã giao`;
  $('customerReviewDenominator').textContent=`${number(current.reviewed_orders)} đơn có đánh giá`;
  $('lowReviewDenominator').textContent=`${number(current.low_review_orders)} / ${number(current.reviewed_orders)} đơn có đánh giá`;
}

function renderBuyerTrend(trend) {
  const holder=$('buyerTrendChart');holder.replaceChildren();
  if (!trend.length) {holder.textContent='Không có dữ liệu.';return;}
  const svg=svgElement('svg',{viewBox:'0 0 720 260',preserveAspectRatio:'none',role:'img'});
  const left=55,right=686,top=20,bottom=210,width=right-left,height=bottom-top;
  const max=Math.max(...trend.map((row)=>Number(row.buyers)),1)*1.12;
  for(let i=0;i<4;i++){
    const yy=top+i*height/3;svg.append(svgElement('line',{x1:left,y1:yy,x2:right,y2:yy,stroke:'#edf1ef'}));
    const label=svgElement('text',{x:3,y:yy+4,fill:'#98a6a9','font-size':10});label.textContent=number(Math.round(max*(1-i/3)));svg.append(label);
  }
  const step=width/trend.length;
  trend.forEach((row,i)=>{
    const returning=Number(row.previously_observed_buyers),first=Math.max(0,Number(row.buyers)-returning);
    const x=left+step*(i+.5),barWidth=Math.min(step*.6,31);
    const firstHeight=first/max*height,returningHeight=returning/max*height;
    const base=svgElement('rect',{x:x-barWidth/2,y:bottom-firstHeight,width:barWidth,height:firstHeight,fill:'#8bcebd'});
    const tip=svgElement('title');tip.textContent=`${monthLabel(row.month_key)}: ${number(first)} mới quan sát, ${number(returning)} đã mua trước tháng`;base.append(tip);svg.append(base);
    if(returningHeight)svg.append(svgElement('rect',{x:x-barWidth/2,y:bottom-firstHeight-returningHeight,width:barWidth,height:returningHeight,fill:'#d68b63'}));
    const label=svgElement('text',{x,y:238,'text-anchor':'middle',fill:'#98a6a9','font-size':10});label.textContent=`${String(row.month_key).slice(4)}/${String(row.month_key).slice(2,4)}`;svg.append(label);
  });
  addMonthTargets(svg,trend.map((row)=>row.month_key),trend.map((_,i)=>left+step*(i+.5)),step,top,238,
    trend.map((row)=>`${number(row.buyers)} người mua`));
  holder.append(svg);
}

function renderReviewTrend() {
  if (!dashboard) return;
  const holder=$('reviewTrendChart');holder.replaceChildren();
  const metric=$('reviewTrendMetric').value,trend=dashboard.customer.trend;
  const values=trend.map((row)=>row.reviewed_orders ? (metric==='review_score' ? Number(row.review_score_sum)/row.reviewed_orders : row.low_review_orders/row.reviewed_orders) : null);
  const available=values.filter((value)=>value!==null);
  if(!available.length){holder.textContent='Không có đơn có đánh giá trong kỳ lọc.';return;}
  const svg=svgElement('svg',{viewBox:'0 0 720 260',preserveAspectRatio:'none',role:'img'});
  const left=72,right=686,top=20,bottom=210,width=right-left,height=bottom-top;
  const max=metric==='review_score'?5:Math.max(...available,.01)*1.12;
  const min=metric==='review_score'?1:0;
  const y=(value)=>bottom-(value-min)/(max-min)*height;
  const format=(value)=>metric==='review_score'?`${decimal(value,2)}/5`:`${decimal(value*100,1)}%`;
  for(let i=0;i<4;i++){
    const yy=top+i*height/3;svg.append(svgElement('line',{x1:left,y1:yy,x2:right,y2:yy,stroke:'#edf1ef'}));
    const label=svgElement('text',{x:3,y:yy+4,fill:'#98a6a9','font-size':10});label.textContent=format(max-(max-min)*i/3);svg.append(label);
  }
  const x=(i)=>left+(trend.length===1?width/2:i*width/(trend.length-1));
  values.forEach((value,i)=>{
    if(i&&values[i-1]!==null&&value!==null)svg.append(svgElement('line',{x1:x(i-1),y1:y(values[i-1]),x2:x(i),y2:y(value),stroke:'#d87e54','stroke-width':3}));
    if(value!==null){const dot=svgElement('circle',{cx:x(i),cy:y(value),r:4,fill:'#d87e54'});const tip=svgElement('title');tip.textContent=`${monthLabel(trend[i].month_key)}: ${format(value)} · n=${number(trend[i].reviewed_orders)}`;dot.append(tip);svg.append(dot);}
    const label=svgElement('text',{x:x(i),y:238,'text-anchor':'middle',fill:'#98a6a9','font-size':10});label.textContent=`${String(trend[i].month_key).slice(4)}/${String(trend[i].month_key).slice(2,4)}`;svg.append(label);
  });
  addMonthTargets(svg,trend.map((row)=>row.month_key),trend.map((_,i)=>x(i)),width/Math.max(trend.length-1,1),top,238,
    values.map((value)=>value===null?'Không có dữ liệu':format(value)));
  holder.append(svg);
}

function renderCustomerSegments(segments) {
  const holder=$('customerSegmentRows');holder.replaceChildren();
  segments.forEach((row)=>{
    const tr=document.createElement('tr');
    const mean=row.reviewed_orders?Number(row.review_score_sum)/row.reviewed_orders:null;
    const values=[row.segment==='first'?'Đơn đầu tiên quan sát':'Đơn mua tiếp theo',number(row.orders),number(row.buyers),compactValue(row.ordered_item_value),percent(row.late_orders,row.eligible_orders),mean===null?'—':`${decimal(mean,2)}/5`,percent(row.low_review_orders,row.reviewed_orders)];
    values.forEach((value)=>{const td=document.createElement('td');td.textContent=value;tr.append(td);});holder.append(tr);
  });
  if(!segments.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=7;td.textContent='Không có dữ liệu trong kỳ lọc.';tr.append(td);holder.append(tr);}
}

function renderDeliveryReviews(groups) {
  const holder=$('deliveryReviewCards');holder.replaceChildren();
  [['on_time','Đúng hoặc trước hạn'],['late','Giao trễ theo ngày']].forEach(([key,label])=>{
    const row=groups.find((item)=>item.delivery_group===key);
    const card=document.createElement('article');card.className='panel experience-card';
    const title=document.createElement('span');title.textContent=label;
    const score=document.createElement('strong');score.textContent=row?.reviewed_orders?`${decimal(Number(row.review_score_sum)/row.reviewed_orders,2)}/5`:'—';
    const detail=document.createElement('p');detail.textContent=row?`${number(row.reviewed_orders)} đơn có đánh giá / ${number(row.eligible_orders)} đơn đủ điều kiện`:'Không có đơn đủ điều kiện';
    const low=document.createElement('small');low.textContent=`Đánh giá thấp (≤2): ${row?percent(row.low_review_orders,row.reviewed_orders):'—'}`;
    card.append(title,score,detail,low);holder.append(card);
  });
}

function renderExperienceBreakdown() {
  if(!dashboard)return;
  const dimension=$('experienceDimension').value;
  const rows=dashboard.customer.breakdowns[dimension];
  const holder=$('experienceBreakdownRows');holder.replaceChildren();
  rows.forEach((row)=>{
    const tr=document.createElement('tr');if(row.reviewed_orders<20)tr.className='small-sample';
    const mean=row.reviewed_orders?Number(row.review_score_sum)/row.reviewed_orders:null;
    const values=[groupName(dimension,row.label),number(row.orders),number(row.reviewed_orders),mean===null?'—':`${decimal(mean,2)}/5`,percent(row.low_review_orders,row.reviewed_orders),percent(row.late_orders,row.eligible_orders),percent(row.delivered_reviewed_orders,row.delivered_orders)];
    values.forEach((value)=>{const td=document.createElement('td');td.textContent=value;tr.append(td);});holder.append(tr);
  });
  if(!rows.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=7;td.textContent='Không có dữ liệu trong kỳ lọc.';tr.append(td);holder.append(tr);}
}

function renderOverviewCategories(categories, totalValue) {
  const holder = $('overviewCategoryRows'); holder.replaceChildren();
  const total = Number(totalValue || 0);
  if (!total) { holder.textContent = 'Không có giá trị sản phẩm trong kỳ lọc.'; holder.classList.add('empty'); return; }
  holder.classList.remove('empty');
  const top = categories.slice(0, 5).map((row) => ({key:row.category_name,label: String(row.category_name || 'Không rõ').replaceAll('_', ' '), value: Number(row.ordered_item_value)}));
  const rest = Math.max(0, total - top.reduce((sum, row) => sum + row.value, 0));
  if (rest > 0) top.push({label: 'Các danh mục còn lại', value: rest});
  top.forEach(({key, label, value}) => {
    const row = document.createElement(key ? 'button' : 'div'); row.className = 'overview-mix-row';
    if (key) {
      row.type='button'; row.title=`Xem danh mục ${label}`;
      row.addEventListener('click',()=>{
        $('categoryTrendSelect').value=key;
        $('categorySearch').value=label;
        renderCategoryTrend(); renderCategoryTable();
        location.hash='products';
      });
    }
    const name = document.createElement('strong'); name.textContent = label;
    const track = document.createElement('div'); track.className = 'overview-mix-track';
    const fill = document.createElement('span'); fill.style.width = `${100 * value / total}%`;
    track.append(fill);
    const amount = document.createElement('span'); amount.textContent = `${compactValue(value)} · ${percent(value, total)}`;
    row.append(name, track, amount); holder.append(row);
  });
}

function renderPredictions(data) {
  const {summary, metadata} = data;
  $('predictionOrders').textContent = number(summary.orders);
  $('predictionDays').textContent = summary.mean_predicted_days === null ? '—' : `${decimal(summary.mean_predicted_days, 1)} ngày`;
  $('predictionManual').textContent = number(summary.manual_calls);
  $('predictionAutomated').textContent = number(summary.automated_messages);
  $('predictionMonitor').textContent = number(summary.monitor_only);
  $('predictionInvalid').textContent = `${number(summary.invalid_regression_outputs)} đầu ra số ngày âm được loại khỏi trung bình.`;
  $('predictionMae').textContent = decimal(metadata.regression_validation_mae_days, 2);
  $('predictionAuc').textContent = decimal(metadata.classification_test_roc_auc, 3);
  $('predictionAp').textContent = decimal(metadata.classification_test_average_precision, 3);
  $('predictionCapacity').textContent = number(metadata.policy_default_manual_capacity_per_shift);
  const parts = [data.filters.month === 'all' ? '07–08/2018' : monthLabel(data.filters.month)];
  if (data.filters.state !== 'all') parts.push(`bang ${data.filters.state}`);
  if (data.filters.order_id) parts.push(`đơn ${data.filters.order_id}`);
  $('predictionCohort').textContent = parts.join(' · ');
  document.querySelectorAll('[data-prediction-action]').forEach((card)=>{
    const active=predictionAction===card.dataset.predictionAction;
    card.classList.toggle('selected',active);
    card.setAttribute('aria-pressed',String(active));
  });
  $('predictionClearAction').hidden=predictionAction==='all';
  const focus=data.hotspots[0];
  $('predictionFocus').textContent=!summary.orders?'Không có đơn trong nhóm lọc.'
    : data.filters.state!=='all'?`Tại bang ${data.filters.state}: ${number(summary.manual_calls)} đơn ưu tiên gọi, ${number(summary.automated_messages)} đơn có thể nhắc tự động.`
    : focus?`Bang ${focus.customer_state} có nhiều đơn ưu tiên gọi nhất trong nhóm đang xem: ${number(focus.manual_calls)} trên ${number(focus.orders)} đơn.`:'';

  const weekly=$('predictionWeekly');weekly.replaceChildren();
  if(!data.weekly.length) weekly.textContent='Không có dữ liệu theo tuần.';
  else {
    const max=Math.max(...data.weekly.map((row)=>Number(row.orders)),1);
    data.weekly.forEach((row)=>{
      const item=document.createElement('div');item.className='prediction-week';
      const count=document.createElement('strong');count.textContent=number(row.orders);
      const track=document.createElement('div');track.className='prediction-week-track';
      const stack=document.createElement('div');stack.className='prediction-week-stack';stack.style.height=`${100*Number(row.orders)/max}%`;
      for(const [className,value] of [['red',row.manual_calls],['yellow',row.automated_messages],['green',Number(row.orders)-Number(row.manual_calls)-Number(row.automated_messages)]]){
        const segment=document.createElement('span');segment.className=className;segment.style.height=`${100*Number(value)/Math.max(Number(row.orders),1)}%`;stack.append(segment);
      }
      track.append(stack);
      const label=document.createElement('small');label.textContent=row.week_start;
      item.title=`Tuần ${row.week_start}: ${number(row.manual_calls)} gọi, ${number(row.automated_messages)} nhắc, ${number(row.orders)} đơn`;
      item.append(count,track,label);weekly.append(item);
    });
  }
  const states=$('predictionStateRows');states.replaceChildren();
  if(!data.hotspots.length) states.textContent='Không có dữ liệu theo bang.';
  else data.hotspots.forEach((row)=>{
    const item=document.createElement('button');item.type='button';item.className='prediction-state-row';
    const name=document.createElement('strong');name.textContent=row.customer_state;
    const detail=document.createElement('span');detail.textContent=`${number(row.manual_calls)} gọi · ${number(row.automated_messages)} nhắc`;
    const total=document.createElement('small');total.textContent=`${number(row.orders)} đơn`;
    item.append(name,detail,total);
    item.addEventListener('click',()=>{$('predictionState').value=row.customer_state;refreshPredictions();});
    states.append(item);
  });

  const actionCounts={all:summary.orders,manual_call:summary.manual_calls,automated_message:summary.automated_messages,none:summary.monitor_only};
  const actionNames={all:'mọi nhóm',manual_call:'ưu tiên gọi điện',automated_message:'nhắc tự động',none:'tiếp tục theo dõi'};
  $('predictionQueueHint').textContent=`Hiển thị ${number(data.orders.length)} trong ${number(actionCounts[predictionAction])} đơn ${actionNames[predictionAction]} có điểm cao nhất.`;
  const holder = $('predictionRows'); holder.replaceChildren();
  data.orders.forEach((row) => {
    const tr = document.createElement('tr');
    const predicted = Number(row.predicted_delivery_days);
    const values = [actionNames[row.action],row.order_id,row.customer_state,row.purchase_timestamp,
      row.promised_delivery_days === null ? '—' : `${decimal(row.promised_delivery_days,1)} ngày`,
      predicted < 0 ? 'Không hợp lệ' : `${decimal(predicted,1)} ngày`,
      decimal(row.delay_score,3)];
    values.forEach((value,index) => {
      const td = document.createElement('td');
      if (index===1) {
        const button=document.createElement('button');button.type='button';button.className='order-detail-button';
        button.textContent=value;button.setAttribute('aria-label',`Xem hai dự báo cho đơn ${value}`);
        button.addEventListener('click',()=>openPredictionDetail(row));td.append(button);
      } else td.textContent=value;
      if(index===0)td.className=`action-label ${row.risk_zone}`;
      tr.append(td);
    });
    if (predicted < 0) tr.classList.add('prediction-invalid');
    holder.append(tr);
  });
  if (!data.orders.length) {
    const tr=document.createElement('tr'), td=document.createElement('td');
    td.colSpan=7; td.textContent='Không tìm thấy đơn trong nhóm lọc.'; tr.append(td); holder.append(tr);
  }
}

function openPredictionDetail(row) {
  const predicted=Number(row.predicted_delivery_days);
  $('predictionDetailTitle').textContent=`Đơn ${row.order_id}`;
  $('predictionDetailContext').textContent=`Đặt ngày ${row.purchase_timestamp} · Bang ${row.customer_state} · Hẹn giao ${row.promised_delivery_days === null ? 'không rõ' : `${decimal(row.promised_delivery_days,1)} ngày`}`;
  $('predictionDetailDays').textContent=predicted<0?'Đầu ra không hợp lệ':`${decimal(predicted,1)} ngày`;
  $('predictionDetailScore').textContent=decimal(row.delay_score,3);
  const actions={manual_call:'Gợi ý: ưu tiên liên hệ trực tiếp',automated_message:'Gợi ý: gửi nhắc tự động',none:'Gợi ý: tiếp tục theo dõi'};
  $('predictionDetailAlert').textContent=actions[row.action];
  $('predictionDetailAlert').classList.toggle('alert',row.action==='manual_call');
  $('predictionDetail').showModal();
}

async function refreshPredictions() {
  if ($('predictionDetail').open) $('predictionDetail').close();
  const params = new URLSearchParams({month:$('predictionMonth').value,state:$('predictionState').value,order_id:$('predictionOrderId').value.trim(),action:predictionAction});
  showNotice('Đang đọc kết quả hai mô hình…');
  try {
    const response = await json(`/api/predictions?${params}`);
    if (!Array.isArray(response.weekly) || !Array.isArray(response.hotspots)
      || typeof response.summary?.manual_calls !== 'number'
      || typeof response.summary?.automated_messages !== 'number'
      || typeof response.summary?.monitor_only !== 'number') {
      throw new Error('Máy chủ dashboard đang dùng phiên bản cũ. Hãy khởi động lại máy chủ rồi tải lại trang.');
    }
    predictionData = response;
    const stateSelect = $('predictionState'), selected = stateSelect.value;
    if (stateSelect.options.length === 1) {
      predictionData.options.states.forEach((state) => { const option=document.createElement('option'); option.value=state; option.textContent=state; stateSelect.append(option); });
      stateSelect.value=selected;
    }
    renderPredictions(predictionData); showNotice('');
  } catch (error) { showNotice(error.message,true); }
}

function currentPage() { return pageInfo[location.hash.slice(1)] ? location.hash.slice(1) : 'overview'; }

function renderToolbar(filters) {
  const holder=$('filterSummary');holder.replaceChildren();
  const label=document.createElement('span');label.className='filter-summary-label';label.textContent='Đang xem';holder.append(label);
  for (const [key,prefix,id] of [['state','Bang','state'],['status','Trạng thái','status']]) {
    if (filters[key] === 'all') continue;
    const chip=document.createElement('button');chip.type='button';chip.className='filter-chip';
    chip.textContent=`${prefix}: ${filters[key]} ×`;
    chip.setAttribute('aria-label',`Bỏ lọc ${prefix.toLowerCase()} ${filters[key]}`);
    chip.addEventListener('click',()=>{ $(id).value='all'; refresh(); });holder.append(chip);
  }
  if (holder.children.length === 1) {
    const empty=document.createElement('span');empty.className='filter-all';empty.textContent='Tất cả bang và trạng thái';holder.append(empty);
  }
  if (filters.state !== 'all' || filters.status !== 'all' || String(filters.month) !== String(defaults.default_month)) {
    const reset=document.createElement('button');reset.type='button';reset.className='filter-reset';reset.textContent='Đặt lại';
    reset.addEventListener('click',()=>{ $('month').value=String(defaults.default_month);$('state').value='all';$('status').value='all';refresh(); });holder.append(reset);
  }
  $('toolbarMonth').textContent=monthLabel(filters.month);
  const months=defaults.months.map(String), index=months.indexOf(String(filters.month));
  $('previousMonth').disabled=index<=0;
  $('nextMonth').disabled=index<0||index>=months.length-1;
}

function showPage() {
  const page = currentPage();
  document.querySelectorAll('[data-page]').forEach((node) => { node.hidden = !node.dataset.page.split(' ').includes(page); });
  document.querySelectorAll('[data-nav]').forEach((node) => {
    const active = node.dataset.nav === page;
    node.classList.toggle('active', active);
    if (active) node.setAttribute('aria-current','page'); else node.removeAttribute('aria-current');
  });
  [$('pageEyebrow').textContent,$('pageTitle').textContent,$('pageSubtitle').textContent] = pageInfo[page];
  $('trendKicker').textContent=page === 'overview' ? '02 / XU HƯỚNG' : '01 / XU HƯỚNG';
  const isPrediction = page === 'predictions';
  if (!isPrediction && $('predictionDetail').open) $('predictionDetail').close();
  $('globalFilterAnchor').hidden = isPrediction;
  $('updatedAt').hidden = isPrediction;
  $('analysisToolbar').hidden = isPrediction;
  $('partialNote').hidden = isPrediction || !dashboard?.comparison?.month_is_partial;
  $('dataBadge').innerHTML = `<span class="badge-dot"></span> ${isPrediction ? 'Tập test hồi cứu' : 'Dữ liệu lịch sử'}`;
  $('footerSource').textContent = isPrediction ? 'Nguồn: artifact ML trên tập test Olist 07–08/2018.' : 'Nguồn: Gold Olist · Thời gian theo ngày đặt hàng · Giá trị là giá sản phẩm đặt, không phải doanh thu thuần.';
  $('footerScope').textContent = isPrediction ? 'Hai đầu ra mô hình ML · Tập test hồi cứu 07–08/2018' : 'Chỉ số lịch sử thực tế';
  closeFilters();
  if (isPrediction && !predictionData) refreshPredictions();
}

function closeFilters() { $('filterPanel').hidden=true; $('filterToggle').setAttribute('aria-expanded','false'); }

async function refresh() {
  const requestId=++refreshRequest;
  showNotice('Đang cập nhật dữ liệu…');
  const params = new URLSearchParams({month:$('month').value,state:$('state').value,status:$('status').value});
  try {
    const result = await json(`/api/dashboard?${params}`);
    if (requestId !== refreshRequest) return;
    dashboard = result;
    renderKpis(dashboard.comparison);
    renderTrend(dashboard.trend);
    renderStateSummary(dashboard.overview_states);
    renderStages(dashboard.delivery_stages);
    renderDiagnosticHighlights(dashboard);
    renderMatrix();
    renderBreakdown();
    renderCategories(dashboard.categories);
    renderProductSummary(dashboard);
    renderSellers(dashboard);
    renderCustomerKpis(dashboard.customer);
    renderBuyerTrend(dashboard.customer.trend);
    renderReviewTrend();
    renderCustomerSegments(dashboard.customer.segments);
    renderDeliveryReviews(dashboard.customer.delivery_reviews);
    renderExperienceBreakdown();
    renderOverviewCategories(dashboard.categories, dashboard.comparison.current.ordered_item_value);
    renderToolbar(dashboard.filters);
    const count=Number(dashboard.filters.state !== 'all')+Number(dashboard.filters.status !== 'all');
    $('filterCount').hidden=!count; $('filterCount').textContent=String(count);
    closeFilters(); showNotice('');
  } catch (error) { if (requestId === refreshRequest) showNotice(error.message,true); }
}

async function initialize() {
  try {
    defaults=await json('/api/options');
    defaults.months.slice().reverse().forEach((month) => {
      const option=document.createElement('option'); option.value=month; option.textContent=monthLabel(month); $('month').append(option);
    });
    $('month').value=String(defaults.default_month);
    for (const [id,values] of [['state',defaults.states],['status',defaults.statuses]]) {
      values.forEach((value) => { const option=document.createElement('option'); option.value=value; option.textContent=value; $(id).append(option); });
    }
    $('updatedAt').textContent=`Kho cập nhật: ${defaults.database_updated_at.replace('T',' ')}`;
    $('filterToggle').addEventListener('click', () => {
      const open=$('filterPanel').hidden;
      $('filterPanel').hidden=!open; $('filterToggle').setAttribute('aria-expanded',String(open));
    });
    $('filterPanel').addEventListener('submit',(event)=>{event.preventDefault();refresh();});
    $('resetButton').addEventListener('click',()=>{
      $('month').value=String(defaults.default_month); $('state').value='all'; $('status').value='all'; refresh();
    });
    $('previousMonth').addEventListener('click',()=>{const months=defaults.months.map(String);selectMonth(months[months.indexOf($('month').value)-1]);});
    $('nextMonth').addEventListener('click',()=>{const months=defaults.months.map(String);selectMonth(months[months.indexOf($('month').value)+1]);});
    document.addEventListener('click',(event)=>{if (!event.target.closest('.filter-anchor')) closeFilters();});
    $('dimension').addEventListener('change',renderBreakdown);
    $('trendMetric').addEventListener('change',()=>{if (dashboard) renderTrend(dashboard.trend);});
    $('categoryTrendSelect').addEventListener('change',renderCategoryTrend);
    $('categorySearch').addEventListener('input',renderCategoryTable);
    $('reviewTrendMetric').addEventListener('change',renderReviewTrend);
    $('experienceDimension').addEventListener('change',renderExperienceBreakdown);
    $('matrixDimension').addEventListener('change',renderMatrix);
    $('predictionFilters').addEventListener('submit',(event)=>{event.preventDefault();refreshPredictions();});
    document.querySelectorAll('[data-prediction-action]').forEach((card)=>card.addEventListener('click',()=>{
      predictionAction=predictionAction===card.dataset.predictionAction?'all':card.dataset.predictionAction;
      refreshPredictions();
    }));
    $('predictionClearAction').addEventListener('click',()=>{predictionAction='all';refreshPredictions();});
    $('predictionDetailClose').addEventListener('click',()=>$('predictionDetail').close());
    document.querySelectorAll('[data-sort]').forEach((button)=>button.addEventListener('click',()=>{
      if (sortKey===button.dataset.sort) sortDescending=!sortDescending;
      else {sortKey=button.dataset.sort; sortDescending=sortKey!=='label';}
      renderBreakdown();
    }));
    window.addEventListener('hashchange',()=>{showPage();window.scrollTo({top:0,behavior:'smooth'});});
    await refresh(); showPage();
  } catch(error) { showNotice(error.message,true); }
}
initialize();
