"""Build a portable static site with Python's standard library."""
import argparse
import html
import json
import math
import os
import re
import shutil
from datetime import date, datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
escape = lambda value: html.escape(str(value), quote=True)


def article_word_count(article):
    return sum(len(block['text'].split()) for block in article['blocks'] if block['type'] != 'image')


def validate_article_image(image):
    for field in ('src', 'small_src', 'social_src'):
        if field in image:
            path = image[field]
            if not re.fullmatch(r'/assets/[A-Za-z0-9_-]+\.(?:webp|png|jpg)', path) or not (ROOT / path.lstrip('/')).is_file():
                raise ValueError('Article image must reference an existing local asset')
    if not image.get('src') or not image.get('alt', '').strip():
        raise ValueError('Article images require a source and descriptive alt text')
    if any(type(image.get(key)) is not int or image[key] <= 0 for key in ('width', 'height')):
        raise ValueError('Article images require positive integer dimensions')


def analytics_markup(script_url, enabled):
    if not script_url:
        return ''
    if not re.fullmatch(r'https://(?:plausible\.io|stats\.foo\.xyz)/js/pa-[A-Za-z0-9_-]+\.js', script_url):
        raise ValueError('Use a site-specific HTTPS Plausible script URL from plausible.io or stats.foo.xyz')
    if not enabled:
        return ''
    return ('<script async src="' + escape(script_url) + '"></script>'
            '<script>window.plausible=window.plausible||function(){(plausible.q=plausible.q||[]).push(arguments)};'
            'plausible.init=plausible.init||function(i){plausible.o=i||{}};plausible.init();</script>')


def build(output, site_url=None):
    site = json.loads((ROOT / 'content/site.json').read_text())
    base = (site_url if site_url is not None else site['url']).rstrip('/')
    parsed = urlsplit(base)
    if base and (parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.query or parsed.fragment):
        raise ValueError('SITE_URL must be an absolute HTTP(S) URL without a query or fragment')
    prefix = parsed.path.rstrip('/') if base else ''
    local = lambda path: prefix + path
    absolute = lambda path: base + path
    ready = bool(base and not site.get('draft', False))
    analytics_url = os.environ.get('PLAUSIBLE_SCRIPT_URL') or site.get('plausible_script_url', '')
    analytics = analytics_markup(analytics_url, ready and parsed.hostname not in ('localhost', '127.0.0.1', '::1'))
    posts = sorted(site['posts'], key=lambda post: post['date'], reverse=True)
    profile_modified = site.get('profile_modified')
    if profile_modified:
        date.fromisoformat(profile_modified)
    seen = set()
    for post in posts:
        slug = post['slug']
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug) or slug in seen:
            raise ValueError('Invalid or duplicate article slug: ' + slug)
        seen.add(slug)
        for field in ('date', 'modified'):
            if post.get(field):
                date.fromisoformat(post[field])
        if post.get('modified', post['date']) < post['date']:
            raise ValueError('Article modification date precedes publication')
        if post.get('hero'):
            validate_article_image(post['hero'])
        for block in post['blocks']:
            if ';' in block['text']:
                raise ValueError('Article text must not contain semicolons')
            if block['type'] == 'image':
                validate_article_image(block)
    output.mkdir(parents=True, exist_ok=True)
    # Remove only paths recorded by this generator, preserving unrelated files.
    manifest = output / '.generated-files.json'
    if manifest.exists():
        for name in json.loads(manifest.read_text()):
            target = output / name
            if target.resolve().is_relative_to(output.resolve()) and target.is_file():
                target.unlink()
    generated = []

    def write(name, data):
        file = output / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(data, encoding='utf-8')
        generated.append(name)

    for file in (ROOT / 'assets').iterdir():
        if file.is_file():
            target = output / 'assets' / file.name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(file, target)
            generated.append('assets/' + file.name)

    person_id = absolute('/#aaron-kaufman')
    website_id = absolute('/#website')
    person = {'@type': 'Person', '@id': person_id, 'name': site['name'], 'givenName': 'Aaron', 'familyName': 'Kaufman', 'url': absolute('/'), 'mainEntityOfPage': {'@id': absolute('/#webpage')}, 'description': site['about'], 'knowsAbout': ['UNIX', 'FreeBSD', 'Systems engineering', 'Information security', 'Linux', 'Server hardening']}
    author = {'@type': 'Person', '@id': person_id, 'name': site['name'], 'url': absolute('/')}
    if site['links']:
        person['sameAs'] = [link['url'] for link in site['links']]

    def page(title, description, path, content, article=None, missing=False, indexable=True):
        url = absolute(path)
        hero = article.get('hero') if article else None
        social = absolute(hero.get('social_src', hero['src'])) if hero else absolute('/assets/social-card.png')
        social_width, social_height = (hero['width'], hero['height']) if hero else (1200, 630)
        social_alt = hero['alt'] if hero else 'Aaron Kaufman: Systems engineering and information security'
        robots = 'index,follow,max-image-preview:large' if ready and not missing and indexable else 'noindex,follow'
        meta = f'<link rel="canonical" href="{escape(url)}">' if base and not missing else ''
        meta += f'<meta name="robots" content="{robots}">'
        graph = [person, {'@type': 'WebSite', '@id': website_id, 'name': site['name'], 'url': absolute('/'), 'inLanguage': 'en', 'publisher': {'@id': person_id}}]
        page_type = {'/': 'ProfilePage', '/about/': 'AboutPage', '/blog/': 'CollectionPage'}.get(path, 'WebPage')
        webpage = {'@type': page_type, '@id': url + '#webpage', 'url': url, 'name': title, 'description': description, 'isPartOf': {'@id': website_id}, 'inLanguage': 'en'}
        if path in ('/', '/about/'):
            webpage['mainEntity'] = {'@id': person_id}
            if profile_modified:
                webpage['dateModified'] = profile_modified
        if path == '/blog/':
            webpage['mainEntity'] = {'@type': 'ItemList', 'itemListElement': [
                {'@type': 'ListItem', 'position': index, 'name': post['title'], 'url': absolute('/blog/' + post['slug'] + '/')}
                for index, post in enumerate(posts, 1)
            ]}
        crumbs = [{'@type': 'ListItem', 'position': 1, 'name': site['name'], 'item': absolute('/')}]
        if path == '/about/':
            crumbs.append({'@type': 'ListItem', 'position': 2, 'name': 'About', 'item': url})
        if path.startswith('/blog/'):
            crumbs.append({'@type': 'ListItem', 'position': 2, 'name': 'Writing', 'item': absolute('/blog/')})
        if article:
            crumbs.append({'@type': 'ListItem', 'position': 3, 'name': article['title'], 'item': url})
            webpage['mainEntity'] = {'@id': url + '#article'}
            graph.append({'@type': 'BlogPosting', '@id': url + '#article', 'url': url, 'mainEntityOfPage': {'@id': url + '#webpage'}, 'headline': article['title'], 'description': description, 'datePublished': article['date'], 'dateModified': article.get('modified', article['date']), 'author': author, 'publisher': {'@id': person_id}, 'inLanguage': 'en', 'articleSection': article['category'], 'wordCount': article_word_count(article)})
            if hero:
                graph[-1]['image'] = {'@type': 'ImageObject', 'url': social, 'width': social_width, 'height': social_height}
            meta += f'<meta property="article:published_time" content="{escape(article["date"])}"><meta property="article:modified_time" content="{escape(article.get("modified", article["date"]))}">'
        if len(crumbs) > 1:
            graph.append({'@type': 'BreadcrumbList', '@id': url + '#breadcrumbs', 'itemListElement': crumbs})
            webpage['breadcrumb'] = {'@id': url + '#breadcrumbs'}
        graph.append(webpage)
        if base and not missing:
            meta += '<script type="application/ld+json">' + json.dumps({'@context': 'https://schema.org', '@graph': graph}, ensure_ascii=False).replace('<', '\\u003c') + '</script>'
        if base:
            meta += f'<meta property="og:url" content="{escape(url)}"><meta property="og:image" content="{escape(social)}"><meta property="og:image:width" content="{social_width}"><meta property="og:image:height" content="{social_height}"><meta property="og:image:alt" content="{escape(social_alt)}"><meta name="twitter:image" content="{escape(social)}"><meta name="twitter:image:alt" content="{escape(social_alt)}">'
        current = ' aria-current="page"' if path == '/blog/' else ''
        writing_nav = f'<a href="{local('/blog/')}"{current}>Writing</a>' if posts else ''
        about_current = ' aria-current="page"' if path == '/about/' else ''
        about_nav = f'<a href="{local('/about/')}"{about_current}>About</a>'
        rss_link = f'<a href="{local('/feed.xml')}">RSS</a>' if posts else ''
        feed_discovery = f'<link rel="alternate" type="application/rss+xml" title="Aaron Kaufman: Writing" href="{local('/feed.xml')}">' if posts else ''
        theme_boot = (ROOT / 'assets/theme-init.js').read_text()
        return f'''<!doctype html>
<html lang="en" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><meta name="description" content="{escape(description)}"><meta name="author" content="{escape(site['name'])}">
<meta name="color-scheme" content="light dark"><meta name="theme-color" content="#eff1f5">
<script>{theme_boot}</script><link rel="preload" href="{local('/assets/space-grotesk.woff2')}" as="font" type="font/woff2" crossorigin><link rel="stylesheet" href="{local('/assets/style.css')}"><script src="{local('/assets/theme.js')}" defer></script><script src="{local('/assets/contacts.js')}" defer></script>
<link rel="icon" href="{local('/assets/favicon.ico')}" sizes="16x16 32x32 48x48"><link rel="icon" href="{local('/assets/favicon-48.png')}" type="image/png" sizes="48x48"><link rel="icon" href="{local('/assets/favicon.svg')}" type="image/svg+xml" sizes="any"><link rel="apple-touch-icon" href="{local('/assets/apple-touch-icon.png')}" sizes="180x180">{feed_discovery}
<meta property="og:site_name" content="{escape(site['name'])}"><meta property="og:locale" content="en_US"><meta property="og:title" content="{escape(title)}"><meta property="og:description" content="{escape(description)}"><meta property="og:type" content="{'article' if article else 'website'}"><meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{escape(title)}"><meta name="twitter:description" content="{escape(description)}">{meta}{analytics if not missing else ''}</head>
<body class="{'home' if path == '/' else 'inner'}"><a class="skip" href="#main">Skip to content</a><div class="wrap"><header class="site-header"><a class="brand" href="{local('/')}" aria-label="Aaron Kaufman: home"><span class="monogram" aria-hidden="true">AK</span><span class="brand-name">{escape(site['name'])}</span></a><nav class="main-nav" aria-label="Main">{about_nav}{writing_nav}<label class="theme-control" hidden><span class="sr-only">Color theme</span><select id="theme" aria-label="Color theme"><option value="light">Latte</option><option value="dark">Mocha</option></select></label></nav></header>
<main id="main">{content}</main><footer><span>© {date.today().year} {escape(site['name'])}</span><div><a href="{local('/about/')}">About</a>{rss_link}<a href="{local('/sitemap.xml')}">Sitemap</a><a href="https://github.com/aaronkaufman" rel="me">GitHub ↗</a></div></footer></div></body></html>'''

    def listing(items):
        rows = []
        for post in items:
            rows.append(f'<li><div class="post-meta"><span>{escape(post["category"])}</span><time datetime="{post["date"]}">{date.fromisoformat(post["date"]).strftime("%b %d, %Y")}</time></div><h3><a class="post-title" href="{local("/blog/" + post["slug"] + "/")}">{escape(post["title"])} <span aria-hidden="true">↗</span></a></h3><p>{escape(post["description"])}</p></li>')
        return '<ul class="post-list">' + ''.join(rows) + '</ul>'

    def article_image(image, hero=False):
        responsive = ''
        if image.get('small_src'):
            responsive = f' srcset="{local(image["small_src"])} {image["width"] // 2}w, {local(image["src"])} {image["width"]}w" sizes="(max-width: 772px) calc(100vw - 32px), 740px"'
        loading = 'loading="eager" fetchpriority="high"' if hero else 'loading="lazy"'
        return f'<figure class="article-image"><img src="{local(image["src"])}"{responsive} width="{image["width"]}" height="{image["height"]}" alt="{escape(image["alt"])}" {loading} decoding="async"><figcaption>{escape(image.get("text", ""))}</figcaption></figure>'

    email_icon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect x="3" y="5" width="18" height="14"/><path d="m3 6 9 7 9-7"/></svg>'
    signal_icon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><circle cx="12" cy="11" r="9" stroke-dasharray="2 3"/><path d="M18 11a6 6 0 0 1-6 6H9l-4 3 1-5a6 6 0 1 1 12-4Z"/></svg>'
    contact_items = []
    if site.get('email'):
        email = escape(site['email'])
        contact_items.append(f'<a class="contact-icon" href="mailto:{email}" aria-label="Email {email}" title="Email: {email}">{email_icon}</a>')
    if site.get('signal'):
        signal = escape(site['signal'])
        contact_items.append(f'<details class="signal-contact"><summary class="contact-icon" aria-label="Show Signal username: {signal}" title="Signal: {signal}">{signal_icon}</summary><div class="contact-popover">Signal<button type="button" class="signal-close" aria-label="Close Signal contact" hidden>×</button><input class="signal-handle" type="text" aria-label="Signal username" value="{signal}" readonly><p class="signal-help">Find me by username in Signal.</p><button type="button" class="signal-copy" hidden>Copy username</button><p class="contact-status" role="status" aria-live="polite"></p></div></details>')
    linkedin = next((link['url'] for link in site['links'] if link['label'] == 'LinkedIn'), None)
    if linkedin:
        linkedin_icon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect x="3" y="3" width="18" height="18"/><path d="M7 10v7m4-7v7m0-4a3 3 0 0 1 6 0v4"/><circle cx="7" cy="7" r=".8" fill="currentColor" stroke="none"/></svg>'
        contact_items.append(f'<a class="contact-icon" href="{escape(linkedin)}" rel="me" aria-label="Aaron Kaufman on LinkedIn" title="LinkedIn">{linkedin_icon}</a>')
    contacts = '<div class="contacts" role="group" aria-label="Contact Aaron Kaufman">' + ''.join(contact_items) + '</div>' if contact_items else ''

    writing_button = f'<a class="button secondary" href="{local('/blog/')}">Writing <span aria-hidden="true">→</span></a>' if posts else ''
    avatar = f'<picture class="splash-portrait"><source type="image/webp" srcset="{local('/assets/avatar-192.webp')} 192w, {local('/assets/avatar-384.webp')} 384w" sizes="(max-width: 760px) 96px, 184px"><img src="{local('/assets/avatar.png')}" width="184" height="184" alt="Illustrated avatar wearing a FreeBSD cap, with blue eyes, glasses, and a full grey beard" decoding="async"></picture>'
    home = f'''<section class="splash" aria-labelledby="splash-title"><div class="splash-content"><p class="eyebrow">Systems engineering / Infosec</p><h1 id="splash-title">Aaron <span>Kaufman</span></h1><p class="intro" id="about">{escape(site['about'])}</p><div class="splash-links"><a class="button" href="https://github.com/aaronkaufman" rel="me">GitHub <span aria-hidden="true">↗</span></a>{writing_button}</div>{contacts}</div>{avatar}</section>'''
    write('index.html', page('Aaron Kaufman | Systems Engineering & Information Security', site['description'], '/', home))
    blog = '<section class="hero compact"><p class="eyebrow">Aaron Kaufman / Writing</p><h1>Writing by Aaron Kaufman.</h1><p class="intro">Systems engineering and information security. Mostly asking why this has root access.</p></section><section class="section"><h2>Articles</h2><div>' + (listing(posts) if posts else '<p>No articles published yet.</p>') + '</div></section>'
    write('blog/index.html', page('Writing by Aaron Kaufman | Linux & Security', 'Writing by Aaron Kaufman on systems engineering and information security.', '/blog/', blog, indexable=bool(posts)))
    about_portrait = f'<picture class="about-portrait"><source type="image/webp" srcset="{local('/assets/avatar-384.webp')} 384w, {local('/assets/avatar-768.webp')} 768w" sizes="(max-width: 760px) min(160px, calc((100vw - 76px) * .4)), (max-width: 1044px) calc((100vw - 156px) * .44), 384px"><img src="{local('/assets/avatar.png')}" width="384" height="384" alt="Illustrated Aaron Kaufman avatar with a FreeBSD cap, glasses, and a grey beard" fetchpriority="high" decoding="async"></picture>'
    about = f'''<section class="about-page" aria-labelledby="about-title"><p class="eyebrow">About</p><div class="about-copy">{about_portrait}<h1 id="about-title">Aaron Kaufman.</h1><p class="intro">I write about UNIX and FreeBSD, with occasional detours into Linux. Topics include system performance, server hardening, networking, cryptography, and privacy. I also cover information security, operational security, open-source intelligence, and layer 8, the people behind the systems.</p><p>Mostly asking why this has root access.</p><div class="splash-links"><a class="button" href="https://github.com/aaronkaufman" rel="me">GitHub <span aria-hidden="true">↗</span></a>{writing_button}</div>{contacts}</div></section>'''
    write('about/index.html', page('About Aaron Kaufman | Systems Engineering & Information Security', 'About Aaron Kaufman: UNIX, FreeBSD, systems engineering, information security, and privacy. Read his writing or get in touch.', '/about/', about))
    paths = [('/', profile_modified), ('/about/', profile_modified)]
    if posts:
        paths.append(('/blog/', max([post.get('modified', post['date']) for post in posts] + ([profile_modified] if profile_modified else []))))
    for post in posts:
        path = '/blog/' + post['slug'] + '/'
        paths.append((path, post.get('modified', post['date'])))
        body, toc = [], []
        for index, block in enumerate(post['blocks']):
            kind, text = block['type'], escape(block['text'])
            if kind == 'image':
                body.append(article_image(block))
                continue
            if kind not in ('p', 'h2', 'h3', 'pre', 'blockquote'):
                raise ValueError('Unsupported content block: ' + kind)
            anchor = ''
            if kind == 'h2':
                slug = re.sub(r'[^a-z0-9]+', '-', block['text'].lower()).strip('-') + '-' + str(index)
                anchor = f' id="{slug}"'
                toc.append(f'<li><a href="#{slug}">{text}</a></li>')
            citation = ''
            if block.get('source'):
                source = block['source']
                if urlsplit(source['url']).scheme != 'https':
                    raise ValueError('Sources must use HTTPS')
                citation = f' <a class="source" href="{escape(source["url"])}">{escape(source["label"])}</a>'
            if kind == 'pre':
                body.append(f'<pre tabindex="0"><code>{text}</code></pre>')
            else:
                body.append(f'<{kind}{anchor}>{text}{citation}</{kind}>')
        minutes = max(1, math.ceil(article_word_count(post) / 220))
        related = ''.join(f'<li><a href="{local("/blog/" + other["slug"] + "/")}">{escape(other["title"])}</a></li>' for other in posts if other['slug'] != post['slug'])
        hero_image = article_image(post['hero'], hero=True) if post.get('hero') else ''
        related_section = f'<aside class="related"><h2>Related reading</h2><ul>{related}</ul></aside>' if related else ''
        content = f'''<article class="article"><nav class="breadcrumbs" aria-label="Breadcrumb"><a href="{local('/')}">Aaron Kaufman</a><span aria-hidden="true">/</span><a href="{local('/blog/')}">Writing</a><span aria-hidden="true">/</span><span aria-current="page">{escape(post['category'])}</span></nav><p class="eyebrow">{escape(post['category'])}</p><h1>{escape(post['title'])}</h1><p class="lede">{escape(post['description'])}</p><div class="byline"><a rel="author" href="{local('/')}">Aaron Kaufman</a><time datetime="{post['date']}">{date.fromisoformat(post['date']).strftime('%B %d, %Y')}</time><span>{minutes} min read</span></div>{hero_image}<nav class="toc" aria-label="On this page"><p>On this page</p><ol>{''.join(toc)}</ol></nav><div class="prose">{''.join(body)}</div><aside class="author-note" aria-label="About the author"><h2>About Aaron Kaufman</h2><p>Aaron Kaufman writes about systems engineering and information security, with notes on Linux and server hardening.</p><a rel="author" href="{local('/about/')}">About Aaron Kaufman</a></aside>{related_section}</article>'''
        write(path.lstrip('/') + 'index.html', page(post['title'] + ' | Aaron Kaufman', post['description'], path, content, post))
    write('404.html', page('Page not found | Aaron Kaufman', 'This page could not be found.', '/404.html', f'<section class="hero"><p class="eyebrow">404</p><h1>Page not found.</h1><a class="button" href="{local("/")}">Back home ↗</a></section>', missing=True))
    sitemap = ET.Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')
    if ready:
        for path, modified in paths:
            entry = ET.SubElement(sitemap, 'url')
            ET.SubElement(entry, 'loc').text = absolute(path)
            if modified:
                ET.SubElement(entry, 'lastmod').text = modified
    write('sitemap.xml', ET.tostring(sitemap, encoding='unicode', xml_declaration=True))
    write('robots.txt', 'User-agent: *\n' + (f'Allow: /\nSitemap: {absolute("/sitemap.xml")}\n' if ready else 'Disallow: /\n'))
    rss = ET.Element('rss', version='2.0', attrib={'xmlns:atom': 'http://www.w3.org/2005/Atom'})
    channel = ET.SubElement(rss, 'channel')
    for tag, text in [('title', 'Aaron Kaufman: Systems & Security'), ('link', absolute('/')), ('description', site['description']), ('language', 'en')]:
        ET.SubElement(channel, tag).text = text
    ET.SubElement(channel, 'atom:link', href=absolute('/feed.xml'), rel='self', type='application/rss+xml')
    for post in posts:
        item = ET.SubElement(channel, 'item')
        url = absolute('/blog/' + post['slug'] + '/')
        for tag, text in [('title', post['title']), ('link', url), ('description', post['description']), ('category', post['category'])]:
            ET.SubElement(item, tag).text = text
        ET.SubElement(item, 'guid', isPermaLink='true').text = url
        ET.SubElement(item, 'pubDate').text = format_datetime(datetime.fromisoformat(post['date']).replace(tzinfo=timezone.utc))
    write('feed.xml', ET.tostring(rss, encoding='unicode', xml_declaration=True))
    write('.nojekyll', '')
    manifest.write_text(json.dumps(generated))
    print(f'Built {len(paths)} pages at {output} for {base or "local preview"}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--url', default=os.environ.get('SITE_URL'))
    args = parser.parse_args()
    build(args.output, args.url)
