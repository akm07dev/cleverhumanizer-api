import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto('https://cleverhumanizer.ai', wait_until='domcontentloaded')
        
        await page.locator('.ql-editor').first.click()
        await page.keyboard.type('This is a dummy text string designed specifically to be long enough to bypass the thirty word minimum limit imposed by the upstream API. By sending this text, we ensure that the warm-up call succeeds and properly initializes the browser session without throwing any HTTP 422 validation errors along the way.')
        await page.locator('.submitQuill').first.click()
        
        print('Waiting 10s for Turnstile...')
        await asyncio.sleep(10)
        
        target_frame = None
        for f in page.frames:
            if 'challenges.cloudflare.com' in f.url:
                target_frame = f
                break
                
        if target_frame:
            print('Found frame! Attempting to click body...')
            try:
                # try clicking the checkbox wrapper first
                box = target_frame.locator('input[type="checkbox"]')
                if await box.count() > 0:
                    print('Input checkbox found!')
                    await box.click(force=True, delay=100)
                else:
                    print('Input checkbox not found, clicking body...')
                    await target_frame.locator('body').click(force=True, delay=100)
                print('Click executed!')
            except Exception as e:
                print('Error clicking:', e)
        else:
            print('Turnstile frame not found!')
            
        await asyncio.sleep(5)
        await browser.close()

asyncio.run(run())
