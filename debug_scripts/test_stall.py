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
        
        print('Waiting 5s before loop...')
        await asyncio.sleep(5)
        
        for i in range(15):
            print(f'--- Loop {i} ---')
            
            # Dismiss Oops
            try:
                oops = await page.get_by_text('Oops! An error occurred').all()
                if oops and await oops[0].is_visible():
                    print('Dismissing Oops')
                    await page.keyboard.press('Escape')
                    await page.keyboard.press('Enter')
            except:
                pass
                
            # Check Turnstile
            frames = [f for f in page.frames if 'challenges.cloudflare.com' in f.url]
            if frames:
                print('Found Turnstile frame! Clicking body')
                await frames[0].locator('body').click(force=True)
            else:
                print('No Turnstile frame found.')
                
            await asyncio.sleep(2)
            
        print('Dumping DOM state...')
        await page.screenshot(path='stall.png')
        html = await page.content()
        with open('stall.html', 'w', encoding='utf-8') as f:
            f.write(html)
            
        await browser.close()

asyncio.run(run())
