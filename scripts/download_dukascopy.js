const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const PAIR = process.env.PAIR;
const TEST_MODE = process.env.TEST_MODE === 'true';
const START_YEAR = 2019;
const TIMEFRAME = 'm15';
const PRICE_TYPE = 'bid'; // Only bid as requested
const RAW_DIR = path.join(__dirname, '..', 'data', 'raw', PAIR, TIMEFRAME, PRICE_TYPE);

// Fast batch settings
const BATCH_SIZE = 50;
const BATCH_PAUSE = 500;
const RETRIES = 5;

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function printHelpAndSettings() {
  console.log(`\n=== dukascopy-node Help & Settings for ${PAIR} ===`);
  try {
    const help = execSync(`npx dukascopy-node --help`, { encoding: 'utf8' });
    // Extract only the relevant lines for the log
    const lines = help.split('\n').filter(l => 
      l.includes('batch-size') || l.includes('batch-pause') || l.includes('retries')
    );
    console.log(lines.join('\n'));
    console.log(`\n[CONFIG] Using batch-size: ${BATCH_SIZE}, batch-pause: ${BATCH_PAUSE}ms, retries: ${RETRIES}\n`);
  } catch (err) {
    console.error("Could not fetch help output.");
  }
}

async function downloadYear(year, isCurrentYear) {
  fs.mkdirSync(RAW_DIR, { recursive: true });
  
  const from = `${year}-01-01`;
  const to = isCurrentYear ? new Date().toISOString().split('T')[0] : `${year}-12-31`;

  // Check if file exists
  const existingFiles = fs.readdirSync(RAW_DIR).filter(f => f.includes(year.toString()));
  if (existingFiles.length > 0) {
    console.log(`[SKIP] ${PAIR} ${year} (file exists)`);
    return;
  }

  for (let attempt = 1; attempt <= RETRIES; attempt++) {
    try {
      const cmd = `npx dukascopy-node -i ${PAIR} -from ${from} -to ${to} -t ${TIMEFRAME} -p ${PRICE_TYPE} -f csv -dir ${RAW_DIR} -bs ${BATCH_SIZE} -bp ${BATCH_PAUSE}`;
      console.log(`[DL] ${PAIR} ${year} (attempt ${attempt})`);
      
      // 20-minute timeout per command
      execSync(cmd, { stdio: 'inherit', timeout: 1200000 }); 
      
      const filesAfter = fs.readdirSync(RAW_DIR);
      const newFile = filesAfter.find(f => f.includes(year.toString()));
      
      if (newFile) {
        const filePath = path.join(RAW_DIR, newFile);
        console.log(`\n[VERIFY] ${newFile}`);
        
        // Print first and last timestamps
        try {
          const head = execSync(`head -n 2 ${filePath}`, { encoding: 'utf8' });
          const tail = execSync(`tail -n 1 ${filePath}`, { encoding: 'utf8' });
          console.log(`First: ${head.split('\n')[1] || 'empty'}`);
          console.log(`Last:  ${tail}`);
          
          // Verify Dec 31 for full years
          if (!isCurrentYear && !tail.includes(`${year}-12-31`)) {
            console.log(`⚠️ Warning: Dec 31 not found in tail for ${year}.`);
          }
        } catch (e) {
          console.log(`Could not read file for verification.`);
        }
        console.log(`[OK] ${PAIR} ${year} downloaded.\n`);
        return;
      }
    } catch (err) {
      console.error(`[ERROR] ${PAIR} ${year} (attempt ${attempt}): ${err.message}`);
    }
    
    if (attempt < RETRIES) {
      const backoff = Math.pow(2, attempt) * 1000;
      console.log(`  Retrying in ${backoff}ms...`);
      await sleep(backoff);
    }
  }
  console.error(`[GIVE UP] ${PAIR} ${year}`);
}

async function main() {
  if (!PAIR) {
    console.error("No PAIR environment variable set.");
    process.exit(1);
  }

  printHelpAndSettings();

  if (TEST_MODE) {
    console.log(`TEST MODE: Downloading only 2019 for ${PAIR}`);
    await downloadYear(2019, false);
    return;
  }

  const currentYear = new Date().getFullYear();

  for (let year = START_YEAR; year <= currentYear; year++) {
    await downloadYear(year, year === currentYear);
  }
  console.log(`\n=== All downloads complete for ${PAIR} ===`);
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
