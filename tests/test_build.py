import importlib.util
import json
import shutil
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('site_builder', ROOT / 'build.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links = []
        self.ids = set()
        self.h1 = 0
        self.canonical = None
        self.robots = ''
        self.schema = []
        self.in_schema = False
        self.images = []
        self.meta = {}
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        if tag == 'h1':
            self.h1 += 1
        if tag == 'img':
            self.images.append(attrs)
            for candidate in attrs.get('srcset', '').split(','):
                if candidate.strip():
                    self.links.append(candidate.strip().split()[0])
        if tag == 'meta':
            self.meta[attrs.get('property', attrs.get('name'))] = attrs.get('content')
        if tag in ('a', 'link', 'script', 'img'):
            self.links.append(attrs.get('href', attrs.get('src', '')))
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical = attrs['href']
        if tag == 'meta' and attrs.get('name') == 'robots':
            self.robots = attrs['content']
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.in_schema = True

    def handle_data(self, text):
        if self.in_schema:
            self.schema.append(json.loads(text))

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_schema = False


class BuildTests(unittest.TestCase):
    def test_root_and_project_urls_links_and_metadata(self):
        posts = json.loads((ROOT / 'content/site.json').read_text())['posts']
        for base in ('https://aaronkaufman.com', 'https://aaronkaufman.github.io/aaronkaufman.com'):
            with self.subTest(base=base), tempfile.TemporaryDirectory() as directory:
                out = Path(directory)
                builder.build(out, base)
                prefix = urlsplit(base).path
                docs = {f.relative_to(out).as_posix(): Document(f.read_text()) for f in out.rglob('*.html')}
                self.assertEqual(set(docs), {'index.html', 'about/index.html', 'blog/index.html', '404.html'} | {'blog/' + p['slug'] + '/index.html' for p in posts})
                for filename, doc in docs.items():
                    self.assertEqual(doc.h1, 1, filename)
                    tracker = 'https://stats.foo.xyz/js/pa-J3iPtMFdQ3_drmLVJCkqA.js'
                    if filename == '404.html':
                        self.assertIsNone(doc.canonical)
                        self.assertIn('noindex', doc.robots)
                        self.assertNotIn(tracker, doc.links)
                    else:
                        expected = base + '/' + filename.removesuffix('index.html')
                        self.assertEqual(doc.canonical, expected)
                        if filename == 'blog/index.html' and not posts:
                            self.assertIn('noindex', doc.robots)
                        else:
                            self.assertNotIn('noindex', doc.robots)
                        self.assertTrue(doc.schema)
                        self.assertEqual(doc.links.count(tracker), 1)
                    for link in doc.links:
                        parts = urlsplit(link)
                        if parts.scheme or parts.netloc or not link:
                            continue
                        if parts.path:
                            self.assertTrue(parts.path.startswith(prefix + '/'), link)
                            relative = parts.path[len(prefix):].lstrip('/')
                            if not relative or relative.endswith('/'):
                                relative += 'index.html'
                        else:
                            relative = filename
                        self.assertTrue((out / relative).is_file(), link)
                        if parts.fragment:
                            self.assertIn(parts.fragment, docs[relative].ids, link)
                sitemap = ET.parse(out / 'sitemap.xml')
                urls = [item.text for item in sitemap.findall('.//{*}loc')]
                expected_urls = {base + '/', base + '/about/'}
                if posts:
                    expected_urls |= {base + '/blog/'} | {base + '/blog/' + p['slug'] + '/' for p in posts}
                self.assertEqual(set(urls), expected_urls)
                self.assertTrue(all(url.startswith(base + '/') for url in urls))
                rss = ET.parse(out / 'feed.xml')
                self.assertEqual(len(rss.findall('.//item')), len(posts))
                self.assertIn(base + '/sitemap.xml', (out / 'robots.txt').read_text())
                self.assertTrue((out / 'assets/social-card.png').is_file())
                self.assertTrue((out / 'assets/space-grotesk.woff2').is_file())
                home_graph = docs['index.html'].schema[0]['@graph']
                profile = next(node for node in home_graph if node['@type'] == 'ProfilePage')
                author = next(node for node in home_graph if node['@type'] == 'Person')
                self.assertEqual(profile['mainEntity']['@id'], author['@id'])
                self.assertEqual(author['name'], 'Aaron Kaufman')
                self.assertIn('https://github.com/aaronkaufman', author['sameAs'])
                self.assertIn('https://www.linkedin.com/in/aakaufman', author['sameAs'])
                self.assertIn('https://www.linkedin.com/in/aakaufman', docs['index.html'].links)
                self.assertEqual(author['mainEntityOfPage']['@id'], profile['@id'])
                self.assertEqual(profile['dateModified'], '2026-11-02')
                about = docs['about/index.html']
                about_node = next(n for n in about.schema[0]['@graph'] if n['@type'] == 'AboutPage')
                self.assertEqual(about_node['mainEntity']['@id'], author['@id'])
                self.assertEqual(about.images[0]['width'], '384')
                self.assertIn(base + '/about/', urls)
                self.assertIn(prefix + '/about/', docs['index.html'].links)
                blog_graph = docs['blog/index.html'].schema[0]['@graph']
                collection = next(node for node in blog_graph if node['@type'] == 'CollectionPage')
                listed = collection['mainEntity']['itemListElement']
                self.assertEqual([item['position'] for item in listed], list(range(1, len(listed) + 1)))
                self.assertEqual({item['url'] for item in listed}, set(urls) - {base + '/', base + '/about/', base + '/blog/'})
                self.assertTrue(all(sitemap.find('.//{*}url[{*}loc="' + url + '"]/{*}lastmod') is not None for url in urls))
                for post in posts:
                    article = docs['blog/' + post['slug'] + '/index.html']
                    node = next(n for n in article.schema[0]['@graph'] if n['@type'] == 'BlogPosting')
                    self.assertEqual(node['wordCount'], builder.article_word_count(post))
                    figures = ([post['hero']] if post.get('hero') else []) + [b for b in post['blocks'] if b['type'] == 'image']
                    self.assertEqual(len(article.images), len(figures))
                    for actual, expected in zip(article.images, figures):
                        self.assertEqual(actual['alt'], expected['alt'])
                        self.assertEqual(actual['width'], str(expected['width']))
                        self.assertEqual(actual['height'], str(expected['height']))
                    if post.get('hero'):
                        hero = post['hero']
                        self.assertEqual(node['image']['url'], base + hero.get('social_src', hero['src']))
                        self.assertEqual(article.meta['og:image'], node['image']['url'])
                        self.assertEqual(article.images[0]['fetchpriority'], 'high')
                        self.assertEqual(article.images[0]['loading'], 'eager')
                        self.assertTrue(all(i['loading'] == 'lazy' for i in article.images[1:]))

    def test_article_image_validation_and_word_count(self):
        valid = {'src': '/assets/avatar.png', 'alt': 'Illustrated avatar', 'width': 384, 'height': 384}
        builder.validate_article_image(valid)
        for change in ({'src': '/assets/../build.py'}, {'src': '/assets/missing.png'}, {'alt': ''}, {'width': 0}, {'small_src': 'https://example.com/image.webp'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                builder.validate_article_image(valid | change)
        self.assertEqual(builder.article_word_count({'blocks': [{'type': 'p', 'text': 'Two words'}, {'type': 'image', 'text': 'A caption excluded from the count'}]}), 2)

    def test_removing_last_article_cleans_pages_feed_and_sitemap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            (root / 'content').mkdir(parents=True)
            shutil.copytree(ROOT / 'assets', root / 'assets')
            site = json.loads((ROOT / 'content/site.json').read_text())
            site['posts'] = [{'slug': 'example-note', 'title': 'Example note',
                              'description': 'A test fixture.', 'date': '2026-11-02',
                              'category': 'Notes', 'blocks': [{'type': 'p', 'text': 'Example content.'}]}]
            content = root / 'content/site.json'
            content.write_text(json.dumps(site))
            out = Path(directory) / 'output'
            base = 'https://aaronkaufman.com'
            with patch.object(builder, 'ROOT', root):
                builder.build(out, base)
                article_file = out / 'blog/example-note/index.html'
                article = Document(article_file.read_text())
                graph = article.schema[0]['@graph']
                post = next(node for node in graph if node['@type'] == 'BlogPosting')
                person = next(node for node in graph if node['@type'] == 'Person')
                self.assertEqual(post['author']['@id'], person['@id'])
                self.assertEqual(post['author']['name'], 'Aaron Kaufman')
                self.assertEqual(post['author']['url'], base + '/')
                self.assertEqual(post['url'], article.canonical)
                self.assertNotIn('noindex', Document((out / 'blog/index.html').read_text()).robots)
                self.assertEqual(len(ET.parse(out / 'feed.xml').findall('.//item')), 1)
                site['posts'] = []
                content.write_text(json.dumps(site))
                builder.build(out, base)
            self.assertFalse(article_file.exists())
            self.assertIn('noindex', Document((out / 'blog/index.html').read_text()).robots)
            self.assertEqual(len(ET.parse(out / 'feed.xml').findall('.//item')), 0)
            self.assertEqual([item.text for item in ET.parse(out / 'sitemap.xml').findall('.//{*}loc')], [base + '/', base + '/about/'])

    def test_analytics_requires_valid_site_specific_script_and_enabled_build(self):
        script = 'https://plausible.io/js/pa-test123.js'
        self.assertEqual(builder.analytics_markup('', True), '')
        self.assertEqual(builder.analytics_markup(script, False), '')
        markup = builder.analytics_markup(script, True)
        self.assertIn('async src="' + script + '"', markup)
        self.assertIn('plausible.init()', markup)
        self.assertNotIn('<iframe', markup)
        custom = 'https://stats.foo.xyz/js/pa-J3iPtMFdQ3_drmLVJCkqA.js'
        self.assertIn('async src="' + custom + '"', builder.analytics_markup(custom, True))
        for invalid in ['http://plausible.io/js/pa-test.js', 'https://example.com/script.js', 'https://stats.foo.xyz.evil.example/js/pa-test.js', 'https://plausible.io/js/pa-test.js" onload="alert(1)']:
            with self.assertRaises(ValueError):
                builder.analytics_markup(invalid, True)

    def test_stale_generated_pages_removed_without_removing_user_files(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            builder.build(out, 'https://example.com')
            manifest = out / '.generated-files.json'
            generated = json.loads(manifest.read_text())
            (out / 'old-post.html').write_text('old generated page')
            (out / 'keep.txt').write_text('unrelated file')
            manifest.write_text(json.dumps(generated + ['old-post.html']))
            builder.build(out, 'https://example.com')
            self.assertFalse((out / 'old-post.html').exists())
            self.assertEqual((out / 'keep.txt').read_text(), 'unrelated file')

    def test_local_preview_is_not_indexable(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            builder.build(out, '')
            doc = Document((out / 'index.html').read_text())
            self.assertIn('noindex', doc.robots)
            self.assertIsNone(doc.canonical)
            self.assertFalse(any('stats.foo.xyz' in link for link in doc.links))

    def test_localhost_preview_omits_configured_analytics(self):
        for url in ('http://localhost:8000', 'http://127.0.0.1:8000', 'http://[::1]:8000'):
            with self.subTest(url=url), tempfile.TemporaryDirectory() as directory:
                out = Path(directory)
                builder.build(out, url)
                text = (out / 'index.html').read_text()
                self.assertNotIn('stats.foo.xyz', text)
                self.assertNotIn('plausible.init()', text)


if __name__ == '__main__':
    unittest.main()
