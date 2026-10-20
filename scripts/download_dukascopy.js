const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const PAIR = process.env.PAIR;
const TEST_MODE = process.env.TEST_MODE === 'true';
const START_YEAR = 2019;
const TIMEFRAME = 'm15';
const PRICE_TYPE = 'bid'; 
const RAW_DIR = path.join(__dirname, '..', 'data', 'raw', PAIR, TIMEFRAME, PRICE_TYPE);

const BATCH_SIZE = 50;
const BATCH_PAUSE = 500;
const RETRIES = 5;

let failedYears = [];

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function cleanEmptyFiles() {
  if (!fs.existsSync(RAW_DIR)) return;
  const files = fs.readdirSync(RAW_DIR);
  for (const f of files) {
    const fp = path.join(RAW_DIR, f);
    if (fs.statSync(fp).size < 100) {
      console.log(`[CLEAN] Removing empty/partial file: ${f}`);
      fs.unlinkSync(fp);
    }
  }
}

function printHelpAndSettings() {
  console.log(`\n=== dukascopy-node Help & Settings for ${PAIR} ===`);
  try {
    const help = execSync(`npx dukascopy-node --help`, { encoding: 'utf8' });
    const lines = help.split('\n').filter(l => 
      l.includes('batch-size') || l.includes('batch-pause') || l.includes('retries')
    );
    console.log(lines.join('\n'));
  } catch (err) {}
}

async function downloadYear(year, isCurrentYear) {
  fs.mkdirSync(RAW_DIR, { recursive: true });
  cleanEmptyFiles();
  
  const from = `${year}-01-01`;
  const to = isCurrentYear ? new Date().toISOString().split('T')[0] : `${year}-12-31`;

  // Check if we already have the FULL file for this year
  const existingFiles = fs.readdirSync(RAW_DIR);
  const hasFullYear = existingFiles.some(f => f.includes(from) && f.includes(to));
  
  if (hasFullYear) {
    console.log(`[SKIP] ${PAIR} ${year} (full year file exists)`);
    return;
  }

  for (let attempt = 1; attempt <= RETRIES; attempt++) {
    try {
      const cmd = `npx dukascopy-node -i ${PAIR} -from ${from} -to ${to} -t ${TIMEFRAME} -p ${PRICE_TYPE} -f csv -dir ${RAW_DIR} -bs ${BATCH_SIZE} -bp ${BATCH_PAUSE}`;
      console.log(`[DL] ${PAIR} ${year} (attempt ${attempt})`);
      execSync(cmd, { stdio: 'inherit', timeout: 1200000 }); 
      
      const filesAfter = fs.readdirSync(RAW_DIR);
      // Strict check: filename must contain both the start and end dates
      const newFile = filesAfter.find(f => f.includes(from) && f.includes(to));
      
      if (newFile) {
        const filePath = path.join(RAW_DIR, newFile);
        if (fs.statSync(filePath).size > 100) {
          console.log(`\n[VERIFY] ${newFile}`);
          const head = execSync(`head -n 2 ${filePath}`, { encoding: 'utf8' });
          const tail = execSync(`tail -n 1 ${filePath}`, { encoding: 'utf8' });
          console.log(`First: ${head.split('\n')[1] || 'empty'}`);
          console.log(`Last:  ${tail}`);
          return;
        }
      }
      console.error(`[ERROR] ${PAIR} ${year} downloaded but valid file not found.`);
    } catch (err) {
      console.error(`[ERROR] ${PAIR} ${year} (attempt ${attempt}): ${err.message}`);
    }
    
    if (attempt < RETRIES) {
      await sleep(Math.pow(2, attempt) * 1000);
    }
  }
  
  console.error(`[GIVE UP] ${PAIR} ${year}`);
  failedYears.push(year);
}

async function main() {
  printHelpAndSettings();

  if (TEST_MODE) {
    console.log(`TEST MODE: Downloading only 2019 for ${PAIR}`);
    await downloadYear(2019, false);
  } else {
    const currentYear = new Date().getFullYear();
    for (let year = START_YEAR; year <= currentYear; year++) {
      await downloadYear(year, year === currentYear);
    }
  }
  
  console.log(`\n=== All downloads complete for ${PAIR} ===`);

  if (failedYears.length > 0) {
    console.error(`FAILED YEARS: ${failedYears.join(', ')}`);
    process.exit(1); // Force the GitHub job to turn red
  }
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
