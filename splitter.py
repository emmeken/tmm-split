#!/usr/bin/env python3

from collections import defaultdict
from pathlib import Path
import json
import re

def parse_header(line):
    assert line.startswith("::")
    i = 2
    name_chars = []
    tag_chars = []
    chars = name_chars
    while i < len(line):
        ch = line[i]
        i += 1
        if ch == "[":
            assert chars is name_chars
            chars = tag_chars
        elif ch == "]":
            break
        elif ch == "{":
            i -= 1
            break
        elif ch == "\\":
            ch = line[i]
            i += 1
        chars.append(ch)

    name = "".join(name_chars).strip()
    tags = "".join(tag_chars[1:]).split()
    if i == len(line):
        metadata = {}
    else:
        metadata = json.loads(line[i:])

    return name, tags, metadata


def split_passages(lines):
    header = None
    body = []
    for line in lines:
        line = line.rstrip()
        if line.startswith("::"):
            if header is not None:
                yield *header, body
            header = parse_header(line)
            body = []
        else:
            body.append(line)
    if header is not None:
        yield *header, body


def classify_passage(name, tags, metadata):
    if name in ("StoryTitle", "StorySubtitle", "StorySettings", "StoryCaption", "StoryAuthor", "StoryData"):
        return "metadata.twee"

    if name in ("StoryInit", "StoryMenu", "MenuOptions", "PassageReady", "Bug Report Instructions"):
        return "init.twee"

    if "stylesheet" in tags:
        if name.endswith("font"):
            return "font.css"
        else:
            return "stylesheet.css"

    if "widget" in tags:
        return "widgets.twee"

    if name == "Character Information":
        return "tracking.twee"

    if name in (
        "Start",
        "Check for Age",
        "Incest Toggle",
        "Underage",
        "Reset Preferences.",
        "Instructions and About the Game",
    ) or name.startswith("Beta-testing:"):
        return "start.twee"

    if "script" in tags:
        return {
            "Bug Report": "bugreport.js",
            "savesimport": "savesimport.js",
            "Save Info": "saves.js",
        }[name]

    if name.startswith("Q:") or name == "FAQ":
        assert "nosave" in tags
        return "faq.twee"

    if "nosave" in tags:
        if name.startswith("You") or name == "Basic Description":
            return "you.twee"
        elif name.startswith("Var"):
            return "tracking.twee"
        else:
            return "characters.twee"

    return "unsorted.twee"


def escape(s):
    s = s.replace("\\", "\\\\")
    s = s.replace("[", "\\[").replace("]", "\\]")
    s = s.replace("{", "\\{").replace("}", "\\}")
    return s


def split_body(body):
    pos = 0
    while pos < len(body):
        start = body.find("<<", pos)
        if start == -1:
            yield body[pos :]
            break
        elif pos < start:
            yield body[pos : start]
        end = body.find(">>", start)
        if end == -1:
            print("incomplete macro:", body[start:])
            break
        pos = end + 2
        yield body[start : pos]


re_macro_arg = re.compile(r'[^"\[\s]+|"[^"]*"|\[\[[^\]]*\]\]')


def find_links_in_macro(macro):
    assert macro.startswith("<<")
    assert macro.endswith(">>")
    name, *args = re_macro_arg.findall(macro[2:-2])
    if name == "display":
        assert args[0][0] == '"'
        assert args[0][-1] == '"'
        yield args[0][1:-1]
    elif name == "click":
        if args[0][0] == "[":
            yield from find_links_in_text(args[0])
        else:
            if len(args) == 1:
                link = args[0]
            elif len(args) == 2:
                link = args[1]
            else:
                assert False, args
            assert link[0] == '"'
            assert link[-1] == '"'
            yield link[1:-1]


def find_links_in_text(text):
    pos = 0
    while True:
        start = text.find("[[", pos)
        if start == -1:
            return
        end = text.find("]]", start)
        if end == -1:
            print("incomplete link:", text[start:])
            return
        link = text[start + 2:end]
        sep = link.find("|")
        if sep == -1:
            yield link
        else:
            yield link[sep + 1:]
        pos = end + 2


def find_links(body):
    for segment in split_body("\n".join(body)):
        if segment.startswith("<<"):
            yield from find_links_in_macro(segment)
        else:
            yield from find_links_in_text(segment)


def subgraph(graph, starts, limits):
    def filter_links(links):
        return {link: None for link in links if link not in limits}

    remaining = {name: filter_links(graph[name]) for name in starts}
    reached = {}
    while remaining:
        name, links = next(iter(remaining.items()))
        del remaining[name]
        reached[name] = links
        for link in links:
            if link not in reached:
                remaining[link] = filter_links(graph[link])
    return reached


def order_passages(filename, passages_by_name):
    if not filename.endswith(".twee"):
        names = passages_by_name.keys()
        assert len(passages_by_name) == 1, names
        yield filename, names
        return

    # Build the link graph.
    # Use a dictionary to remove duplicates while preserving insertion order.
    link_to = {
        name: {link: None for link in find_links(body) if link in passages_by_name}
        for name, (tags, body) in passages_by_name.items()
    }
    if False:
        for name, links in link_to.items():
            print(repr(name), "->", list(links.keys()))
        print("-" * 80)

    if filename == "unsorted.twee":
        # The bookmarked (autosave) passages are used as primary split points for the source files.
        # However, as day 3 has so much content, it has been split up further.
        day0_start = ["Introduction"]
        day1_start = ["Monday Morning"]
        day2_start = ["Tuesday Morning"]
        day3_start = ["Wednesday Morning", "Wednesday Morning (1)"]
        end_of_content = ["Sorry, this is the end for now."]
        # The makeover section is shared between day 2 and 3.
        # It is also the separation between the first and second half of day 3.
        makeover_start = ["Accept Mrs. Anderson's help.", "Mrs. Anderson's Makeover", "Wednesday Makeover"]
        makeover_end = ["Go to dinner.", "Makeover Done"]
        yield "day0.twee", order_graph(subgraph(link_to, day0_start, day1_start))
        yield "day1.twee", order_graph(subgraph(link_to, day1_start, day2_start))
        yield "day2.twee", order_graph(subgraph(link_to, day2_start + ["Go to dinner."], day3_start + makeover_start))
        yield "day3-school.twee", order_graph(subgraph(link_to, day3_start, ["Go Home"]))
        yield "day3-afterschool.twee", order_graph(subgraph(link_to, ["Go Home"], makeover_start + ["That sounds good.", "Makeover Done"]))
        yield "day3-tape.twee", order_graph(subgraph(link_to, ["That sounds good."], []))
        dates = {
            "rachel": ["Go out to meet Rachel."],
            "sean": ["Go out to meet Sean."],
            "julia": ["Go shopping with Julia."],
            "billy": ["Go meet Billy."],
            "ethan": ["Go meet Ethan."],
            "belinda": ["Go clubbing with Belinda.", "Go to comedy club with Belinda."],
            "molly": ["Go and find Molly."],
            "emily": ["Absolutely!"],
        }
        date_starts = [passage for starts in dates.values() for passage in starts]
        yield "day3-evening.twee", order_graph(subgraph(link_to, ["Makeover Done", "Sleep Night 3"], date_starts + end_of_content))
        for person, passages in dates.items():
            yield f"day3-date-{person}.twee", order_graph(
                subgraph(link_to, passages, ["Go to Wednesday Dinner", "Sleep Night 3"] + end_of_content)
            )
        yield "end.twee", order_graph(subgraph(link_to, end_of_content, []))
        yield "makeover.twee", order_graph(subgraph(link_to, makeover_start, makeover_end))
    else:
        yield filename, order_graph(link_to)


def order_graph(link_to):
    # Build the inverse link graph.
    # Use a dictionary to get fast lookups while preserving insertion order.
    link_from = {name: {} for name in link_to}
    for name, links in link_to.items():
        for link in links:
            link_from[link][name] = None
    if False:
        for name, links in link_from.items():
            print(repr(name), "<-", list(links.keys()))
        print("-" * 80)

    # Find nodes without remaining incoming links.
    ready = [name for name, links in link_from.items() if not links]
    # Build a stack: the first to be used at the end of the list.
    ready.reverse()
    for name in ready:
        del link_from[name]
    ordered_names = []
    while True:
        # Break the few cycles that exist in the passages graph.
        if not ready:
            for name in (
                "Makeover Options",
                "Rosalind actions",
                "Ask Billy what he and Mr. Anderson talked about last night.",
                "Go to the arcade.",
            ):
                if name in link_from:
                    ready = [name]
                    del link_from[name]
                    break
            else:
                break

        name = ready.pop()
        ordered_names.append(name)

        # Remove links to the popped passage.
        for link in reversed(link_to[name]):
            waiting_on = link_from.get(link)
            if waiting_on is not None:
                del waiting_on[name]
                if not waiting_on:
                    ready.append(link)
                    del link_from[link]

    if link_from:
        # We didn't break all the cycles; report unreachable passages.
        print("=" * 80)
        print("Reachable:")
        for name in ordered_names:
            print(f"  {name!r}")
        print("-" * 80)
        print("Unreachable:")
        for name, links in link_from.items():
            print(f"  {name!r} <- {list(links.keys())}")
        ordered_names += sorted(link_from)

    return ordered_names


def split_file(path):
    passages_by_filename = defaultdict(dict)
    with open(path, "r") as f:
        for name, tags, metadata, body in split_passages(f):
            filename = classify_passage(name, tags, metadata)
            while body and not body[-1]:
                del body[-1]
            assert not metadata  # not used in this game
            passages_by_filename[filename][name] = (tags, body)

    ordered_passages_by_filename = {
        new_filename: {name: passages_by_name[name] for name in ordered_names}
        for old_filename, passages_by_name in passages_by_filename.items()
        for new_filename, ordered_names in order_passages(old_filename, passages_by_name)
    }

    # Check that every original passage ends up in exactly 1 file.
    passage_to_files = {
        name: []
        for filename, passages_by_name in passages_by_filename.items()
        for name in passages_by_name.keys()
    }
    for new_filename, passages_by_name in ordered_passages_by_filename.items():
        for name in passages_by_name.keys():
            passage_to_files[name].append(new_filename)
    lost_passages = sorted(name for name, files in passage_to_files.items() if not files)
    duped_passages = sorted(name for name, files in passage_to_files.items() if len(files) > 1)
    if lost_passages:
        print("Lost passages:")
        for name in lost_passages:
            print(f"- {name}")
    if duped_passages:
        print("Duplicate passages:")
        for name in duped_passages:
            print(f"- {name}: {', '.join(sorted(passage_to_files[name]))}")

    for filename, passages_by_name in ordered_passages_by_filename.items():
        print(f"Writing: {filename}")
        first = True
        src_dir = Path("src")
        src_dir.mkdir(exist_ok=True)
        with open(src_dir / f"{filename}", "w") as out:
            for name, (tags, body) in passages_by_name.items():
                if first:
                    first = False
                else:
                    print("", file=out)
                    print("", file=out)
                if filename.endswith(".twee"):
                    if tags:
                        tags_str = " ".join(escape(tag) for tag in sorted(tags))
                        print(f":: {escape(name)} [{tags_str}]", file=out)
                    else:
                        print(f":: {escape(name)}", file=out)
                for line in body:
                    print(line, file=out)


if __name__ == "__main__":
    split_file("TheMasculineMystique_v0.9.7a.tw")
