#!/usr/bin/env python3


import telebot
import cfg
import utils


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(commands=['start'])
def command_code(message: telebot.types.Message):
    t = r"""
There are a few ways to escape data in different contexts.

<b>In SQL:</b>

• Use the backslash character (\) to escape special characters, such as single quotes (&#x27;), double quotes (&quot;), and backslashes (\). For example:

<pre><code class = "language-sql">INSERT INTO table_name (column_name) VALUES (&#x27;This is a &#x27;&#x27;test&#x27;&#x27;.&#x27;);
</code></pre>
• Use the <code>ESCAPE</code> clause to specify a different character to use for escaping. For example:

<pre><code class = "language-sql">INSERT INTO table_name (column_name) VALUES E&#x27;This is a &#x27;&#x27;test&#x27;&#x27;.&#x27; ESCAPE &#x27;\&#x27;&#x27;;
</code></pre>
<b>In JSON:</b>

• Use the backslash character (\) to escape special characters, such as double quotes (&quot;), backslashes (\), and forward slashes (/). For example:

<pre><code class = "language-json">{
  &quot;name&quot;: &quot;John Doe&quot;,
  &quot;address&quot;: &quot;123 Main Street&quot;,
  &quot;city&quot;: &quot;Anytown, USA&quot;,
  &quot;phone&quot;: &quot;555-123-4567&quot;
}
</code></pre>
• Use the <code>\u</code> escape sequence to represent Unicode characters. For example:

<pre><code class = "language-json">{
  &quot;name&quot;: &quot;John Doe&quot;,
  &quot;address&quot;: &quot;123 Main Street&quot;,
  &quot;city&quot;: &quot;Anytown, USA&quot;,
  &quot;phone&quot;: &quot;555-123-4567&quot;,
  &quot;favorite_emoji&quot;: &quot;\u263a&quot;
}
</code></pre>
<b>In HTML:</b>

• Use the <code>&amp;</code> character followed by the name of the HTML entity to escape special characters, such as less than (&lt;), greater than (&gt;), and ampersand (&amp;). For example:

<pre><code class = "language-html">&lt;p&gt;This is a &amp;lt;strong&amp;gt;test&amp;lt;/strong&amp;gt;.&lt;/p&gt;
</code></pre>
• Use the <code>&amp;#</code> character followed by the decimal or hexadecimal code of the Unicode character to escape Unicode characters. For example:

<pre><code class = "language-html">&lt;p&gt;This is a &amp;#x263a;.&lt;/p&gt;
</code></pre>
<b>In JavaScript:</b>

• Use the backslash character (\) to escape special characters, such as single quotes (&#x27;), double quotes (&quot;), and backslashes (\). For example:

<pre><code class = "language-javascript">var name = &#x27;John Doe&#x27;;
var address = &quot;123 Main Street&quot;;
var city = &#x27;Anytown, USA&#x27;;
var phone = &#x27;555-123-4567&#x27;;
</code></pre>
• Use the <code>\u</code> escape sequence to represent Unicode characters. For example:

<pre><code class = "language-javascript">var favorite_emoji = &#x27;\u263a&#x27;;
</code></pre>
<b>In Python:</b>

• Use the backslash character (\) to escape special characters, such as single quotes (&#x27;), double quotes (&quot;), and backslashes (\). For example:

<pre><code class = "language-python">name = &#x27;John Doe&#x27;
address = &quot;123 Main Street&quot;
city = &#x27;Anytown, USA&#x27;
phone = &#x27;555-123-4567&#x27;
</code></pre>
• Use the <code>\u</code> escape sequence to represent Unicode characters. For example:

<pre><code class = "language-python">favorite_emoji = &#x27;\u263a&#x27;
</code></pre>
<b>In C++:</b>

• Use the backslash character (\) to escape special characters, such as single quotes (&#x27;), double quotes (&quot;), and backslashes (\). For example:

<pre><code class = "language-c++">string name = &quot;John Doe&quot;;
string address = &quot;123 Main Street&quot;;
string city = &quot;Anytown, USA&quot;;
string phone = &quot;555-123-4567&quot;;
</code></pre>
• Use the <code>\u</code> escape sequence to represent Unicode characters. For example:

<pre><code class = "language-c++">string favorite_emoji = &quot;\u263a&quot;;
</code></pre>
<b>In Java:</b>

• Use the backslash character (\) to escape special characters, such as single quotes (&#x27;), double quotes (&quot;), and backslashes (\). For example:

<pre><code class = "language-java">String name = &quot;John Doe&quot;;
String address = &quot;123 Main Street&quot;;
String city = &quot;Anytown, USA&quot;;
String phone = &quot;555-123-4567&quot;;
</code></pre>
• Use the <code>\u</code> escape sequence to represent Unicode characters. For example:

<pre><code class = "language-java">String favorite_emoji = &quot;\u263a&quot;;
</code></pre>
<b>In PHP:</b>

• Use the backslash character (\) to escape special characters, such as single quotes (&#x27;), double quotes (&quot;), and backslashes (\). For example:

<pre><code class = "language-php">$name = &#x27;John Doe&#x27;;
$address = &quot;123 Main Street&quot;;
$city = &#x27;Anytown, USA&#x27;;
$phone = &#x27;555-123-4567&#x27;;
</code></pre>
• Use the <code>\u</code> escape sequence to represent Unicode characters. For example:

<pre><code class = "language-php">$favorite_emoji = &#x27;\u263a&#x27;;
</code></pre>
    """

    
    for x in utils.split_html(t, 1000):
        bot.reply_to(message, x, parse_mode = 'HTML')



if __name__ == '__main__':
    bot.polling()
