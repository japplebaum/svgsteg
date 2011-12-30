#!/usr/bin/python

"""
A proof of concept for embedding secret messages in SVG images.
@author Julian Applebaum
"""

from xml.dom import minidom
from xml.parsers.expat import ExpatError
import random, sys, re

usage_tip = "Usage: \tsvgsteg.py -embed path/to/msg.txt path/to/cover.svg stegokey\n" + \
            "\tsvgsteg.py -extract path/to/stego-object.svg stegokey\n" + \
            "\tsvgsteg.py -capacity path/to/cover.svg\n"
bad_file = "Error: %s is not a valid file\n"
bad_image = "Error: %s is not a valid svg image.\n"

# embed_tags.keys() = all tags with 1 or more attributes containing
#                     numbers suitable for embedding.
# embed_tags[t] = all of t's attributes containing numbers suitable
#                 for embedding
embed_tags = {
    "linearGradient": ["x1", "y1", "x2", "y2"],
    "radialGradient": ["cx", "cy", "r", "gradientTransform"],
    "path": ["d"]
}


def get_svg(file):
    """
    Attempt to parse an SVG file. If it's at least valid XML,
    also validate that its doctype is one of the official SVG specs.
    """
    
    valid_doctypes = [ "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd",
                       "http://www.w3.org/TR/2001/REC-SVG-20010904/DTD/svg10.dtd"]
    try:
        svg = minidom.parse(file)
        doctype = svg.doctype
        assert doctype.systemId in valid_doctypes
    except ExpatError, AssertionError:
        raise ValueError()
    
    return svg


def get_nodes(doc, tags):
    """
    Get every node in doc whose nodeType is in tags.
    """
    
    node_list = []
    
    for tag in tags:
        node_list += doc.getElementsByTagName(tag)
        
    return sorted(node_list)


def get_slots(embed_nodes, embed_tags):
    """
    Get all of the "slots" that embedded bits can be encoded into, i.e.
    all of the floating point numbers appearing in each tag's attributes
    """
    
    # match all floating point numbers
    fp_reg = re.compile(r"[0-9]+\.[0-9]+")
    embed_slots = []
    
    # Traverse the XML document to get a list of all the tags with 
    # embedding slots. Record references to those slots for later.
    for node in embed_nodes:
        for attr in embed_tags[node.tagName]:
            if node.hasAttribute(attr):
                attr_body = node.getAttribute(attr)
                fp_iter = fp_reg.finditer(attr_body)
                for slot in fp_iter:
                    embed_slots.append((node, attr, slot))
    
    return sorted(embed_slots)
 
 
def pad(bin_num, n):
    """
    Pad a bitstring bin_num with leading 0's so that len(bin_num) = n.
    """
    return "0"*(n-len(bin_num)) + bin_num


def embed_bit(bit, embed_slot):
    """
    Replace the LSD of the number at embed_slot with:
    - a random even number if bit = 0
    - a random odd number if bit = 1
    """
    node, attr, slot = embed_slot
    attr_val = node.getAttribute(attr)
    fp_str = attr_val[slot.start():slot.end()]
    lsd = 2 * random.randint(1, 4) + int(bit)
    emb_fp = fp_str[0:len(fp_str)-1] + str(lsd)
    emb_str = attr_val[0:slot.start()] + emb_fp + attr_val[slot.end():]
    node.setAttribute(attr, emb_str)


def extract_bit(embed_slot):
    """
    Extract the bit embedded in a slot.
    """
    
    node, attr, slot = embed_slot
    fp_str = slot.string[slot.start():slot.end()]
    return 0 if int(fp_str[-1]) % 2 == 0 else 1


def do_embed(argv):
    """
    Embed a message in an SVG file and print the resulting XML to stdout
    """
    
    if len(argv) != 3:
        sys.stderr.write(usage_tip)
        return
    
    msg_path = argv[0]
    cover_path = argv[1]
    stego_key = argv[2]
    
    # get the message file
    try:
        msg = open(msg_path, "r")
    except IOError:
        sys.stderr.write(bad_file % msg_path)
        return
        
    # get the cover image  
    try:
        cover = open(cover_path)
    except IOError:
        sys.stderr.write(bad_file % cover_path)
        return
    
    # parse the cover image
    try:
        svg = get_svg(cover)
    except ValueError:
        sys.stderr.write(bad_image % cover_path)
        return
    
    # Get all of the slots for embedding, then randomly shuffle them using the
    # stego-key as the seed. The message bits will be randomly distributed in
    # the resulting XML document
    random.seed(stego_key)
    embed_nodes = get_nodes(svg, embed_tags.keys())
    embed_slots = get_slots(embed_nodes, embed_tags)
    random.shuffle(embed_slots)
    
    # don't want calls to embed_bit to be deterministic
    random.seed()
    
    bitstring = ""

    for ch in msg.read():
        bin_num = pad(bin(ord(ch))[2:], 8)
        bitstring += bin_num
        
    # add 32 bit number signaling length of embedded content
    bitstring = pad(bin(len(bitstring))[2:], 32) + bitstring
        
    # check that there are enough carrier bits for the message
    if len(bitstring) > len(embed_slots):
        sys.stderr.write("Error: message size is greater than carrier capacity.\n")
        return
    
    # embed all of the bits
    for i in range(0, len(bitstring)):
        embed_bit(bitstring[i], embed_slots[i])
    
    # dump to stdout
    print svg.toxml()


def do_extract(argv):
    """
    Extract a message embedded into an SVG file
    """   
     
    if len(argv) != 2:
        sys.stderr.write(usage_tip)
        return
    
    stego_obj_path = argv[0]
    stego_key = argv[1]
    
    try:
        stego_obj = open(stego_obj_path)
    except IOError:
        sys.stderr.write(bad_file % stego_obj_path)
        return
    
    # parse the cover image
    try:
        svg = get_svg(stego_obj_path)
    except ValueError:
        sys.stderr.write(bad_image % stego_obj_path)
        return
    
    # get all of the possible embedding nodes, then shuffle them in the same
    # order that the embedding algorithm did
    random.seed(stego_key)
    embed_nodes = get_nodes(svg, embed_tags.keys())
    embed_slots = get_slots(embed_nodes, embed_tags)
    random.shuffle(embed_slots)

    msg_len = 0
    msg = ""
    
    # extract the length of the message
    for i in range(0, 32):
        msg_len += 2**(31-i) * extract_bit(embed_slots[i])
    
    # if the "message length" is greater than the number of slots, then either
    # the stego_key is wrong, or it's not a valid stego-object
    if msg_len > len(embed_slots):
        sys.stderr.write("Error: Could not extract message. Stego-key incorrect or "
            + "carrier image damaged.\n")
        return
    
    bit = 7
    chr_val = 0
    msg = ""
        
    # reconstruct the message 1 character at a time
    for i in range(32, 32 + msg_len):        
        chr_val += 2**(bit) * extract_bit(embed_slots[i])
        bit -= 1
                
        if bit == -1:
            msg += chr(chr_val)
            chr_val = 0
            bit = 7
               
    print msg


def do_capacity(argv):
    """
    Display the message capacity of a potential cover image
    """
    
    if len(argv) != 1:
        sys.stderr.write(usage_tip)
    
    cover_path = argv[0]
    
    try:
        cover = open(cover_path)
    except IOError:
        sys.stderr.write(bad_file % cover_path)
        return
    
    try:
        svg = get_svg(cover)
    except ValueError:
        sys.stderr.write(bad_image % cover_path)
        return
    
    embed_nodes = get_nodes(svg, embed_tags.keys())
    embed_slots = get_slots(embed_nodes, embed_tags)
    
    # subtract 32 bits for the message size head, divide by 8 for ASCII
    print "Embedding capacity: %i ASCII characters." % ((len(embed_slots)-32)/8)
    

def main(argv):
    if len(argv) == 1:
        sys.stderr.write(usage_tip)
        return
         
    mode = argv[1]
    
    if mode == "-embed":
        do_embed(argv[2:])
    elif mode == "-extract":
        do_extract(argv[2:])
    elif mode == "-capacity":
        do_capacity(argv[2:])
    else:
        sys.stderr.write(usage_tip)
    

if __name__ == '__main__' :
    main(sys.argv)   