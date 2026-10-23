import { describe, it, expect } from 'vitest';
import { inlineMd, blockMd, preMd } from './md';

describe('inlineMd', () => {
  it('formats ***both*** as bold italic, and leaves maths alone', () => {
    expect(inlineMd('a ***key*** idea')).toBe('a <strong><em>key</em></strong> idea');
    expect(inlineMd('x***y')).toBe('x***y');
  });

  it('renders bold, em, and code', () => {
    expect(inlineMd('**Linear algebra** is *the* `softmax(x)`')).toBe(
      '<strong>Linear algebra</strong> is <em>the</em> <code>softmax(x)</code>'
    );
  });

  it('escapes HTML before injecting tags (XSS-safe)', () => {
    expect(inlineMd('<script>alert(1)</script>')).toBe(
      '&lt;script&gt;alert(1)&lt;/script&gt;'
    );
    expect(inlineMd('**<b>x</b>**')).toBe('<strong>&lt;b&gt;x&lt;/b&gt;</strong>');
  });

  it('does not italicise * inside code spans', () => {
    expect(inlineMd('`a*b*c`')).toBe('<code>a*b*c</code>');
  });

  it('leaves plain numbers with spaces untouched', () => {
    expect(inlineMd('build a GPT (Weeks 2 to 5)')).toBe('build a GPT (Weeks 2 to 5)');
  });

  it('handles underscores as emphasis', () => {
    expect(inlineMd('_emphasis_ here')).toBe('<em>emphasis</em> here');
  });

  it('leaves maths and code literal: a marker needs text inside and no letter or digit outside', () => {
    for (const text of [
      'x**2 + y**2',
      '2*3*4',
      '3 * x * y',
      'a * b',
      'snake_case_name and my_var_2',
      'grad_x = d_out * w_t',
      '** not bold **',
      '* not em *',
      'f(x)*g(x)'
    ]) {
      expect(inlineMd(text), text).toBe(text);
    }
  });

  it('still formats emphasis that is written as emphasis', () => {
    expect(inlineMd('ask *why* it works')).toBe('ask <em>why</em> it works');
    expect(inlineMd('this is **bold**, and (*this*)')).toBe('this is <strong>bold</strong>, and (<em>this</em>)');
    expect(inlineMd('**a** and *b*')).toBe('<strong>a</strong> and <em>b</em>');
    expect(inlineMd('see _the mask_.')).toBe('see <em>the mask</em>.');
    expect(inlineMd('**x**2')).toBe('**x**2');
  });

  it('ignores NUL characters, which would collide with the code placeholder', () => {
    const nul = String.fromCharCode(0);
    expect(inlineMd(`${nul}0${nul}`)).toBe('0');
    expect(inlineMd(`a ${nul}0${nul} \`b\``)).toBe('a 0 <code>b</code>');
    expect(blockMd(`x${nul}0${nul}\ny`)).toBe('x0<br>y');
  });
});

describe('preMd', () => {
  it('keeps line breaks and indentation as typed, for a pre-wrap element', () => {
    const text = 'Try this:\n    for row in w:\n        assert row.sum() == 1\nThen **check** it.';
    expect(preMd(text)).toBe('Try this:\n    for row in w:\n        assert row.sum() == 1\nThen <strong>check</strong> it.');
  });

  it('renders fenced code the same way blockMd does, and escapes HTML', () => {
    expect(preMd('Mask:\n```\nx = 1\n```\n<b>done</b>')).toBe('Mask:<code class="md-pre">x = 1</code>&lt;b&gt;done&lt;/b&gt;');
  });

  it('renders "- " and "* " lines as a bulleted list, dropping the line break on either side', () => {
    expect(preMd('Check:\n- the **mask**\n* the `scale`\nThen run it.')).toBe(
      'Check:<ul class="md-list"><li>the <strong>mask</strong></li><li>the <code>scale</code></li></ul>Then run it.'
    );
  });

  it('renders "N. " lines as a numbered list, keeping a start other than 1', () => {
    expect(preMd('1. derive\n2. *code* it')).toBe('<ol class="md-list"><li>derive</li><li><em>code</em> it</li></ol>');
    expect(preMd('3. test it\n4. ship')).toBe('<ol class="md-list" start="3"><li>test it</li><li>ship</li></ol>');
  });

  it('starts a new list when the kind changes, and lets the list margin stand for one blank line around it', () => {
    expect(preMd('- a\n1. b\n\nafter')).toBe('<ul class="md-list"><li>a</li></ul><ol class="md-list"><li>b</li></ol>after');
    expect(preMd('before\n\n- a\n\n\nafter')).toBe('before<ul class="md-list"><li>a</li></ul>\nafter');
    expect(preMd('one\n\ntwo')).toBe('one\n\ntwo');
  });

  it('escapes HTML inside a list item', () => {
    expect(preMd('- <img src=x onerror=alert(1)>\n- **<script>x</script>**')).toBe(
      '<ul class="md-list"><li>&lt;img src=x onerror=alert(1)&gt;</li><li><strong>&lt;script&gt;x&lt;/script&gt;</strong></li></ul>'
    );
    expect(preMd('1. "><svg onload=alert(1)>')).toBe('<ol class="md-list"><li>"&gt;&lt;svg onload=alert(1)&gt;</li></ol>');
  });

  it('leaves lines that only look like list markers as text', () => {
    for (const text of ['-5 is negative', '1.5 is a ratio', '*not a bullet*', '**bold** line', '- ', '2024.', '    - indented code']) {
      expect(preMd(text), text).toBe(inlineMd(text));
    }
    expect(preMd('x = 3\n-5 is negative')).toBe('x = 3\n-5 is negative');
  });

  it('never makes lists inside fenced code', () => {
    expect(preMd('```\n- a\n1. b\n```')).toBe('<code class="md-pre">- a\n1. b</code>');
  });
});

describe('blockMd', () => {
  it('converts newlines to <br>', () => {
    expect(blockMd('line one\nline two')).toBe('line one<br>line two');
  });
});

describe('blockMd fenced code', () => {
  it('renders a fenced block as escaped, unformatted code on its own lines', () => {
    const text = 'Mask first:\n```python\nscores = scores.masked_fill(mask == 0, float("-inf"))\nw = softmax(scores * 2)\n```\nThen softmax.';
    expect(blockMd(text)).toBe(
      'Mask first:<code class="md-pre">scores = scores.masked_fill(mask == 0, float("-inf"))\nw = softmax(scores * 2)</code>Then softmax.'
    );
  });

  it('never lets HTML in a fenced block through', () => {
    expect(blockMd('```\n<img src=x onerror=alert(1)>\n```')).toBe(
      '<code class="md-pre">&lt;img src=x onerror=alert(1)&gt;</code>'
    );
  });

  it('leaves an unclosed fence as text and keeps inline code working beside blocks', () => {
    expect(blockMd('```\nnot closed')).toBe('```<br>not closed');
    expect(blockMd('use `-inf`\n```\nx\n```')).toBe('use <code>-inf</code><code class="md-pre">x</code>');
  });
});
