const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const PAIRS = [
  'eurusd', 'gbpusd', 'usdjpy', 'audusd', 'usdcad', 'usdchf',
  'nzdusd', 'eurjpy', 'gbpjpy', 'eurgbp', 'audjpy'
];
const START_YEAR = 2019;
const TIMEFRAME = 'm15';
const PRICE_TYPES = ['bid', 'ask'];
const RAW_DIR = path.join(__dirname, '..', 'data', 'raw');

const TEST_MODE = process.env.TEST_MODE === 'true';
const TEST_PAIR = process.env.TEST_PAIR || 'eurusd';
const TEST_MONTH = process.env.TEST_MONTH || '2019-01';

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function getMonths(fromYear, fromMonth, toYear, toMonth) {
  const months = [];
  let y = fromYear, m = fromMonth;
  while (y < toYear || (y === toYear && m <= toMonth)) {
    months.push({ year: y, month: m });
    m++;
    if (m > 12) { m = 1; y++; }
  }
  return months;
}

async function downloadMonth(pair, year, month, priceType, retries = 3) {
  const dir = path.join(RAW_DIR, pair, TIMEFRAME, priceType);
  fs.mkdirSync(dir, { recursive: true });
  const filename = `${pair}-${TIMEFRAME}-${priceType}-${year}-${String(month).padStart(2, '0')}-01-${year}-${String(month).padStart(2, '0')}-28.csv`;
  
  // Find the actual file, as dukascopy-node names it slightly differently
  const filesBefore = fs.readdirSync(dir);
  if (filesBefore.length > 0) {
    console.log(`[SKIP] ${pair} ${year}-${month} ${priceType} (already exists)`);
    return;
  }

  const from = `${year}-${String(month).padStart(2, '0')}-01`;
  const nextMonth = month === 12 ? { y: year + 1, m: 1 } : { y: year, m: month + 1 };
  const to = `${nextMonth.y}-${String(nextMonth.m).padStart(2, '0')}-01`;

  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      // Use the locally installed package, not npx
      const cmd = `./node_modules/.bin/dukascopy-node -i ${pair} -from ${from} -to ${to} -t ${TIMEFRAME} -p ${priceType} -f csv -dir ${dir} -v`;
      console.log(`[DL] ${pair} ${year}-${month} ${priceType} (attempt ${attempt})`);
      execSync(cmd, { stdio: 'pipe', timeout: 120000 });
      
      const filesAfter = fs.readdirSync(dir);
      const newFiles = filesAfter.filter(f => !filesBefore.includes(f));

      if (newFiles.length > 0) {
        const newFilePath = path.join(dir, newFiles[0]);
        const stats = fs.statSync(newFilePath);
        if (stats.size > 100) {
          console.log(`[OK] ${pair} ${year}-${month} ${priceType} (${stats.size} bytes)`);
          return;
        } else {
          console.log(`[FAIL] ${pair} ${year}-${month} ${priceType} (Empty file created, size: ${stats.size})`);
          fs.unlinkSync(newFilePath); // delete empty file
        }
      } else {
        console.log(`[FAIL] ${pair} ${year}-${month} ${priceType} (No file created)`);
      }
    } catch (err) {
      console.error(`[ERROR] ${pair} ${year}-${month} ${priceType} (attempt ${attempt}): ${err.message}`);
      if (err.stdout) console.error(err.stdout.toString());
    }
    
    if (attempt < retries) {
      const backoff = Math.pow(2, attempt) * 1000;
      console.log(`  Retrying in ${backoff}ms...`);
      await sleep(backoff);
    }
  }
  console.error(`[GIVE UP] ${pair} ${year}-${month} ${priceType}`);
}

async function main() {
  console.log('=== Dukascopy Download Script ===');
  console.log(`Test mode: ${TEST_MODE}`);

  if (TEST_MODE) {
    const [year, month] = TEST_MONTH.split('-').map(Number);
    console.log(`TEST: Downloading ${TEST_PAIR} for ${year}-${month}`);
    for (const pt of PRICE_TYPES) {
      await downloadMonth(TEST_PAIR, year, month, pt);
    }
    return;
  }

  const now = new Date();
  const months = getMonths(START_YEAR, 1, now.getFullYear(), now.getMonth() + 1);

  for (const pair of PAIRS) {
    console.log(`\n=== Processing ${pair} ===`);
    for (const pt of PRICE_TYPES) {
      for (const { year, month } of months) {
        await downloadMonth(pair, year, month, pt);
      }
    }
  }
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
