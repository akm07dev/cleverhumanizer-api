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
        
        print('Dumping frames...')
        for f in page.frames:
            print('Frame:', f.url)
            
        print('Dumping Turnstile iframes in main page...')
        iframes = await page.locator('iframe').all()
        for iframe in iframes:
            src = await iframe.get_attribute('src')
            print('Iframe SRC:', src)
            
        await browser.close()

asyncio.run(run())
