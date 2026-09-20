import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        response_data = None
        page.on('response', lambda r: print(f'Response: {r.status} {r.url}'))

        await page.goto('https://cleverhumanizer.ai', wait_until='domcontentloaded')
        
        await page.locator('.ql-editor').first.click()
        await page.keyboard.type('This is a dummy text string designed specifically to be long enough to bypass the thirty word minimum limit imposed by the upstream API. By sending this text, we ensure that the warm-up call succeeds and properly initializes the browser session without throwing any HTTP 422 validation errors along the way.', delay=20)
        
        await asyncio.sleep(1)
        await page.locator('.submitQuill').first.click()
        
        print('Waiting 5s for Turnstile/Modal...')
        await asyncio.sleep(5)
        
        # 1. Dismiss Oops modal if it exists
        try:
            btn = page.locator('#limitModal button.greenBtn').first
            if await btn.count() > 0:
                print('Clicking OK on limitModal')
                await btn.click(force=True)
        except Exception as e:
            print(f'Error clicking modal: {e}')
            
        await asyncio.sleep(1)
            
        # 2. Check and click Turnstile if it exists
        frames = [f for f in page.frames if 'challenges.cloudflare.com' in f.url]
        if frames:
            print('Found Turnstile frame! Clicking body')
            await frames[0].locator('body').click(force=True)
        else:
            print('No Turnstile frame found.')
            
        await asyncio.sleep(5)
        
        # 3. Resubmit
        print('Resubmitting form...')
        await page.locator('.submitQuill').first.click()
        
        print('Waiting 10s for response...')
        await asyncio.sleep(10)
        
        await browser.close()

asyncio.run(run())
