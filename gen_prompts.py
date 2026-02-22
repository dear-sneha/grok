import json

TEMPLATE = """A surreal, high-drama red carpet scene featuring "{name}" at a glamorous film premiere. He stands confidently in a perfectly tailored black tuxedo under bright red carpet lights. Paparazzi surround him aggressively, shouting his "are yeh to zombie ban raha hai " in hindi.
As the photographers scream and flashes intensify, something begins to feel wrong.
warm skin tone slowly drains into a blood, Subtle cracked  bloodfull textures appear Darkened blood faintly show on him. With every camera flash, zombie starts attacking. 
The crowd gasps with chaos running hear and there, 
Lighting style: exaggerated cinematic contrast, dramatic red carpet glow mixed with horror-style underlighting.
Camera style: slow dramatic push-ins, quick paparazzi handheld cuts, alternating between glamorous premiere coverage and unsettling horror close-ups.
Atmosphere: blend of celebrity satire and zombie-movie aesthetics.
Sound design: overlapping paparazzi shouting, rapid camera shutter sounds morphing into metallic echoes, suspenseful orchestral music gradually shifting into dark horror tones.
Ultra realistic, cinematic, high detail, dramatic lighting, 4K, shallow depth of field, suspenseful pacing."""

NAMES = [
    "Virat Kohli", "Shah Rukh Khan", "CarryMinati (Ajey Nagar)", "Narendra Modi",
    "Salman Khan", "Shraddha Kapoor", "Mr. Indian Hacker (Dilraj Singh)", "Priyanka Chopra",
    "Alia Bhatt", "Techno Gamerz (Ujjwal Chaurasia)", "M.S. Dhoni", "Akshay Kumar",
    "Bhuvan Bam", "Deepika Padukone", "Ashish Chanchlani", "Prabhas", "Samay Raina",
    "Amitabh Bachchan", "Kangana Ranaut", "Dhruv Rathee", "Allu Arjun", "Sourav Joshi",
    "Ranveer Singh", "Katrina Kaif", "Sandeep Maheshwari", "Ranbir Kapoor", "Rohit Sharma",
    "Kiara Advani", "Triggered Insaan (Nischay Malhan)", "Rashmika Mandanna",
    "Total Gaming (Ajju Bhai)", "Hrithik Roshan", "Neha Kakkar", "Arijit Singh",
    "Technical Guruji (Gaurav Chaudhary)", "Vicky Kaushal", "Hardik Pandya", "Kriti Sanon",
    "Ram Charan", "Flying Beast (Gaurav Taneja)", "Jr NTR", "Round2Hell (Zayn, Nazim, Wasim)",
    "Kapil Sharma", "Vijay Thalapathy", "Crazy XYZ (Amit Sharma)", "Kareena Kapoor Khan",
    "Kartik Aaryan", "Tanmay Bhat", "Samantha Ruth Prabhu", "Tiger Shroff", "Yash",
    "Awez Darbar", "Anushka Sharma", "Harsh Beniwal", "Ayushmann Khurrana", "Diljit Dosanjh",
    "Badshah", "Prajakta Koli (MostlySane)", "Sanya Malhotra", "Rishabh Pant", "Sara Ali Khan",
    "Nora Fatehi", "Ranveer Allahbadia (BeerBiceps)", "Pankaj Tripathi", "Varun Dhawan",
    "Jannat Zubair", "Sunil Chhetri", "Rajkummar Rao", "Dushyant Kukreja", "Disha Patani",
    "Nayanthara", "Manoj Bajpayee", "Anushka Sen", "Suriya", "Kusha Kapila", "Neeraj Chopra",
    "Nawazuddin Siddiqui", "Mythpat (Mithilesh Patankar)", "Jacqueline Fernandez",
    "Mahesh Babu", "Dolly Singh", "Shubman Gill", "Triptii Dimri", "Mumbiker Nikhil",
    "Sonam Kapoor", "Faisal Shaikh (Mr Faisu)", "Ajith Kumar", "Honey Singh", "Riyaz Aly",
    "Esha Gupta", "KL Rahul", "Avneet Kaur", "John Abraham", "Ravi Kishan", "Elvish Yadav",
    "Mrunal Thakur", "Thugesh (Mahesh Keshwala)", "Shahid Kapoor", "Abhishek Bachchan",
    "Fukra Insaan (Abhishek Malhan)", "Tamannaah Bhatia", "Jasprit Bumrah", "Nisha Madhulika",
    "Ananya Panday", "Siddharth Nigam", "Vijay Sethupathi", "Be YouNick (Nikunj Lotia)",
    "Huma Qureshi", "Suryakumar Yadav", "Kajal Aggarwal", "FactTechz (Rajesh Kumar)",
    "Tara Sutaria", "Zakir Khan", "Shreya Ghoshal", "Mortal (Naman Mathur)", "Janhvi Kapoor",
    "Randeep Hooda", "Village Cooking Channel", "Nani", "Komal Pandey", "Aditya Roy Kapur",
    "Suniel Shetty", "Abhi and Niyu", "Bhumi Pednekar", "Mohammed Shami", "Anushka Shetty",
    "Siddhant Chaturvedi", "Urvashi Rautela", "Khan Sir", "Richa Chadha", "Shikhar Dhawan",
    "Masoom Minawala", "Riteish Deshmukh", "Kabita's Kitchen", "Rakul Preet Singh",
    "Gautam Gambhir", "MostlySane (Prajakta Koli)", "Saif Ali Khan", "Sonu Sood",
    "Wanderers Hub (Prerna Malhan)", "Yuzvendra Chahal", "Genelia D'Souza", "CarryIsLive",
    "Bobby Deol", "Smriti Mandhana", "Emiway Bantai", "Dhanush", "Sania Mirza", "P.V. Sindhu",
]

# Deduplicate while preserving order
seen = set()
unique_names = []
for n in NAMES:
    if n not in seen:
        seen.add(n)
        unique_names.append(n)

prompts = [
    {"prompt": TEMPLATE.format(name=name), "images": [], "isConcat": False}
    for name in unique_names
]

with open("prompts.json", "w", encoding="utf-8") as f:
    json.dump(prompts, f, ensure_ascii=False, indent=4)

print(f"Generated {len(prompts)} prompts in prompts.json")
