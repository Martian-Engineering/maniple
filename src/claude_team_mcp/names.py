"""Iconic names module for assigning memorable session names."""

import random

# =============================================================================
# NAME SETS ORGANIZED BY SIZE
# =============================================================================

# Solo icons - artists known by one name
SOLOS: dict[str, list[str]] = {
    "cher": ["Cher"],
    "madonna": ["Madonna"],
    "prince": ["Prince"],
    "beyonce": ["Beyoncé"],
    "bono": ["Bono"],
    "sting": ["Sting"],
    "liberace": ["Liberace"],
    "elvis": ["Elvis"],
    "adele": ["Adele"],
    "rihanna": ["Rihanna"],
    "shakira": ["Shakira"],
    "banksy": ["Banksy"],
    "voltaire": ["Voltaire"],
    "aristotle": ["Aristotle"],
    "plato": ["Plato"],
    "socrates": ["Socrates"],
    "rembrandt": ["Rembrandt"],
    "michelangelo": ["Michelangelo"],
    "napoleon": ["Napoleon"],
    "cleopatra": ["Cleopatra"],
    "gandhi": ["Gandhi"],
    "pele": ["Pelé"],
    "ronaldinho": ["Ronaldinho"],
    "zendaya": ["Zendaya"],
    "lizzo": ["Lizzo"],
    "bjork": ["Björk"],
    "moby": ["Moby"],
    "seal": ["Seal"],
    "enya": ["Enya"],
    "yanni": ["Yanni"],
    # International artists
    "sade": ["Sade"],
    "stromae": ["Stromae"],
    "lorde": ["Lorde"],
    # Historical/cultural icons
    "confucius": ["Confucius"],
    "nefertiti": ["Nefertiti"],
    "hypatia": ["Hypatia"],
    "frida": ["Frida"],
    "oprah": ["Oprah"],
    "basquiat": ["Basquiat"],
    "hokusai": ["Hokusai"],
    # Fiction
    "hiro": ["Hiro Protagonist"],
    "wishbone": ["Wishbone"],
    # Philosophy
    "sartre": ["Sartre"],
    "negarestani": ["Negarestani"],
}

# Dynamic duos - iconic pairs
DUOS: dict[str, list[str]] = {
    "abbott_costello": ["Abbott", "Costello"],
    "simon_garfunkel": ["Simon", "Garfunkel"],
    "laurel_hardy": ["Laurel", "Hardy"],
    "bonnie_clyde": ["Bonnie", "Clyde"],
    "thelma_louise": ["Thelma", "Louise"],
    "tom_jerry": ["Tom", "Jerry"],
    "batman_robin": ["Batman", "Robin"],
    "bert_ernie": ["Bert", "Ernie"],
    "cheech_chong": ["Cheech", "Chong"],
    "penn_teller": ["Penn", "Teller"],
    "chip_dale": ["Chip", "Dale"],
    "ren_stimpy": ["Ren", "Stimpy"],
    "pinky_brain": ["Pinky", "Brain"],
    "rick_morty": ["Rick", "Morty"],
    "beavis_butthead": ["Beavis", "Butthead"],
    "starsky_hutch": ["Starsky", "Hutch"],
    "cagney_lacey": ["Cagney", "Lacey"],
    "tango_cash": ["Tango", "Cash"],
    "rocky_bullwinkle": ["Rocky", "Bullwinkle"],
    "calvin_hobbes": ["Calvin", "Hobbes"],
    "mario_luigi": ["Mario", "Luigi"],
    "sonic_tails": ["Sonic", "Tails"],
    "sherlock_watson": ["Sherlock", "Watson"],
    "frodo_sam": ["Frodo", "Sam"],
    "han_chewie": ["Han", "Chewie"],
    "r2_3po": ["R2D2", "C-3PO"],
    "bill_ted": ["Bill", "Ted"],
    "wayne_garth": ["Wayne", "Garth"],
    "blues_brothers": ["Jake", "Elwood"],
    "key_peele": ["Key", "Peele"],
    "hall_oates": ["Hall", "Oates"],
    "outkast": ["André", "Big Boi"],
    "daft_punk": ["Thomas", "Guy-Man"],
    "flight_concords": ["Bret", "Jemaine"],
    "odd_couple": ["Oscar", "Felix"],
    "peanut_butter_jelly": ["PB", "J"],
    "salt_pepa": ["Salt", "Pepa"],
    "milli_vanilli": ["Fab", "Rob"],
    "wham": ["George", "Andrew"],
    # Literature & mythology
    "don_sancho": ["Don Quixote", "Sancho"],
    "romeo_juliet": ["Romeo", "Juliet"],
    # Film
    "jules_vincent": ["Jules", "Vincent"],
    # Gaming
    "ratchet_clank": ["Ratchet", "Clank"],
    "jak_daxter": ["Jak", "Daxter"],
    "goku_vegeta": ["Goku", "Vegeta"],
    # Science & innovation
    "wright_bros": ["Orville", "Wilbur"],
    "jobs_woz": ["Steve", "Woz"],
    # Philosophy
    "phil_science": ["Peirce", "Kuhn"],
    "pragmatists": ["James", "Rorty"],
    "d_and_g": ["Deleuze", "Guattari"],
    # TV
    "tia_tamera": ["Tia", "Tamera"],
    "statler_waldorf": ["Statler", "Waldorf"],
    "laverne_shirley": ["Laverne", "Shirley"],
    # Star Trek
    "kirk_khan": ["Kirk", "Khan"],
    "picard_q": ["Picard", "Q"],
}

# Terrific trios - famous threesomes
TRIOS: dict[str, list[str]] = {
    "three_stooges": ["Larry", "Moe", "Curly"],
    "destinys_child": ["Beyoncé", "Kelly", "Michelle"],
    "nirvana": ["Kurt", "Krist", "Dave"],
    "the_police": ["Sting", "Andy", "Stewart"],
    "bee_gees": ["Barry", "Robin", "Maurice"],
    "rush": ["Geddy", "Alex", "Neil"],
    "cream": ["Eric", "Jack", "Ginger"],
    "zz_top": ["Billy", "Dusty", "Frank"],
    "green_day": ["Billie", "Mike", "Tré"],
    "blink_182": ["Mark", "Tom", "Travis"],
    "tlc": ["T-Boz", "Left Eye", "Chilli"],
    "supremes": ["Diana", "Mary", "Florence"],
    "charlie_angels": ["Kelly", "Jill", "Sabrina"],
    "powerpuff_girls": ["Blossom", "Bubbles", "Buttercup"],
    "oai_research": ["Ilya", "Dario", "Sam"],
    "southern_reach": ["Biologist", "Control", "Saul"],
    "homeward_bound": ["Shadow", "Chance", "Sassy"],
    "john_dies": ["David", "John", "Amy"],
    "totoro": ["Satsuki", "Mei", "Totoro"],
    "trio_mandili": ["Tatuli", "Tako", "Mariam"],
    # Philosophy
    "vienna_circle": ["Carnap", "Schlick", "Neurath"],
    "ccru": ["Land", "Plant", "Fisher"],
    # Film
    "stalker": ["Stalker", "Writer", "Professor"],
    # Horror
    "pontypool": ["Grant", "Sydney", "Laurel-Ann"],
    # TV/Animation
    "ed_edd_eddy": ["Ed", "Edd", "Eddy"],
    "chipettes": ["Brittany", "Jeanette", "Eleanor"],
    "chipmunks": ["Alvin", "Simon", "Theodore"],
    "animaniacs": ["Yakko", "Wakko", "Dot"],
    "three_musketeers": ["Athos", "Porthos", "Aramis"],
    "three_tenors": ["Luciano", "Plácido", "José"],
    "three_amigos": ["Lucky", "Dusty", "Ned"],
    "hanson": ["Isaac", "Taylor", "Zac"],
    "jonas_brothers": ["Kevin", "Joe", "Nick"],
    "dixie_chicks": ["Natalie", "Martie", "Emily"],
    "trinity": ["Neo", "Trinity", "Morpheus"],
    "good_bad_ugly": ["Blondie", "Angel Eyes", "Tuco"],
    "ghostbusters_og": ["Peter", "Ray", "Egon"],
    "hp_trio": ["Harry", "Ron", "Hermione"],
    "lotr_hunters": ["Aragorn", "Legolas", "Gimli"],
    "fairly_odd": ["Timmy", "Cosmo", "Wanda"],
    # Mythology & folklore
    "three_fates": ["Clotho", "Lachesis", "Atropos"],
    "norns": ["Urd", "Verdandi", "Skuld"],
    "trimurti": ["Brahma", "Vishnu", "Shiva"],
    # Literature
    "bronte_sisters": ["Charlotte", "Emily", "Anne"],
    # Gaming & anime
    "triforce": ["Link", "Zelda", "Ganon"],
    "team_rocket": ["Jessie", "James", "Meowth"],
    "sannin": ["Jiraiya", "Tsunade", "Orochimaru"],
    # TV
    "top_gear": ["Jeremy", "Richard", "James"],
    "trailer_park": ["Julian", "Ricky", "Bubbles"],
    "totally_spies": ["Sam", "Clover", "Alex"],
}

# Fabulous fours - quartets
QUARTETS: dict[str, list[str]] = {
    "beatles": ["John", "Paul", "George", "Ringo"],
    "tmnt": ["Leonardo", "Donatello", "Raphael", "Michelangelo"],
    "fantastic_four": ["Reed", "Sue", "Johnny", "Ben"],
    "a_team": ["Hannibal", "Face", "Murdock", "B.A."],
    "marx_brothers": ["Groucho", "Harpo", "Chico", "Zeppo"],
    "ghostbusters": ["Peter", "Ray", "Egon", "Winston"],
    "hogwarts_founders": ["Godric", "Helga", "Rowena", "Salazar"],
    "horsemen": ["Conquest", "War", "Famine", "Death"],
    "golden_girls": ["Dorothy", "Rose", "Blanche", "Sophia"],
    "sex_city": ["Carrie", "Samantha", "Charlotte", "Miranda"],
    "queen": ["Freddie", "Brian", "Roger", "John"],
    "led_zeppelin": ["Robert", "Jimmy", "John Paul", "Bonzo"],
    "metallica": ["James", "Lars", "Kirk", "Robert"],
    "u2": ["Bono", "Edge", "Adam", "Larry"],
    "red_hot_chili_peppers": ["Anthony", "Flea", "Chad", "John"],
    "coldplay": ["Chris", "Jonny", "Guy", "Will"],
    "radiohead_core": ["Thom", "Jonny", "Colin", "Ed"],
    "south_park": ["Stan", "Kyle", "Cartman", "Kenny"],
    "seinfeld": ["Jerry", "George", "Elaine", "Kramer"],
    "wizard_oz": ["Dorothy", "Scarecrow", "Tinman", "Lion"],
    "big_bang": ["Sheldon", "Leonard", "Howard", "Raj"],
    "who": ["Roger", "Pete", "John", "Keith"],
    "kiss": ["Gene", "Paul", "Ace", "Peter"],
    "motley_crue": ["Vince", "Nikki", "Mick", "Tommy"],
    "van_halen": ["David", "Eddie", "Alex", "Michael"],
    "doors": ["Jim", "Ray", "Robby", "John"],
    "monkees": ["Davy", "Micky", "Michael", "Peter"],
    "crosby_stills": ["David", "Stephen", "Graham", "Neil"],
    "it_crowd": ["Roy", "Moss", "Jen", "Richmond"],
    "mst3k": ["Cambot", "Tom", "Gypsy", "Crow"],
    # Philosophy
    "frankfurt_school": ["Adorno", "Horkheimer", "Marcuse", "Benjamin"],
    # Mythology
    "cardinal_virtues": ["Prudence", "Justice", "Temperance", "Fortitude"],
    "four_winds": ["Boreas", "Notus", "Eurus", "Zephyrus"],
    # Anime
    "team_avatar": ["Aang", "Katara", "Sokka", "Toph"],
    "cowboy_bebop": ["Spike", "Jet", "Faye", "Ed"],
    # TV comedy
    "its_sunny": ["Dennis", "Mac", "Charlie", "Dee"],
    "impractical": ["Joe", "Murr", "Sal", "Q"],
    "schitts_creek": ["Johnny", "Moira", "David", "Alexis"],
    # Music
    "abba": ["Agnetha", "Björn", "Benny", "Frida"],
    "black_sabbath": ["Ozzy", "Tony", "Geezer", "Bill"],
    # Historical
    "mount_rushmore": ["Washington", "Jefferson", "Roosevelt", "Lincoln"],
}

# Famous fives - quintets
QUINTETS: dict[str, list[str]] = {
    "spice_girls": ["Scary", "Sporty", "Baby", "Ginger", "Posh"],
    "breakfast_club": ["Brain", "Athlete", "Basket Case", "Princess", "Criminal"],
    "jackson_5": ["Jackie", "Tito", "Jermaine", "Marlon", "Michael"],
    "nsync": ["Justin", "JC", "Chris", "Joey", "Lance"],
    "backstreet_boys": ["AJ", "Howie", "Nick", "Kevin", "Brian"],
    "one_direction": ["Harry", "Niall", "Liam", "Louis", "Zayn"],
    "new_kids": ["Donnie", "Jordan", "Joey", "Jonathan", "Danny"],
    "new_edition": ["Bobby", "Ralph", "Ricky", "Michael", "Ronnie"],
    "temptations": ["Eddie", "David", "Otis", "Paul", "Melvin"],
    "aerosmith": ["Steven", "Joe", "Tom", "Joey", "Brad"],
    "rolling_stones": ["Mick", "Keith", "Charlie", "Ron", "Bill"],
    "maroon_5_core": ["Adam", "Jesse", "Mickey", "James", "Matt"],
    "ac_dc": ["Angus", "Malcolm", "Brian", "Cliff", "Phil"],
    "foo_fighters_core": ["Dave", "Nate", "Taylor", "Pat", "Chris"],
    "grateful_dead_core": ["Jerry", "Bob", "Phil", "Bill", "Mickey"],
    "power_rangers_og": ["Jason", "Trini", "Zack", "Billy", "Kimberly"],
    "voltron_force": ["Keith", "Lance", "Pidge", "Hunk", "Allura"],
    "planeteers": ["Kwame", "Wheeler", "Linka", "Gi", "Ma-Ti"],
    "scooby_gang": ["Fred", "Daphne", "Velma", "Shaggy", "Scooby"],
    "queer_eye_og": ["Ted", "Kyan", "Thom", "Carson", "Jai"],
    "rat_pack": ["Frank", "Dean", "Sammy", "Peter", "Joey"],
    "yamadas": ["Takashi", "Matsuko", "Shige", "Noboru", "Nonoko"],
}

# Larger ensembles for flexibility
LARGER: dict[str, list[str]] = {
    "monty_python": ["Chapman", "Cleese", "Gilliam", "Idle", "Jones", "Palin"],
    "friends": ["Rachel", "Monica", "Phoebe", "Ross", "Joey", "Chandler"],
    "ocean_eleven": [
        "Danny", "Rusty", "Linus", "Basher", "Yen",
        "Virgil", "Turk", "Frank", "Reuben", "Livingston", "Saul",
    ],
    "fellowship": [
        "Frodo", "Sam", "Merry", "Pippin", "Gandalf",
        "Aragorn", "Legolas", "Gimli", "Boromir",
    ],
    "avengers_og": [
        "Tony", "Steve", "Thor", "Bruce", "Natasha", "Clint",
    ],
    "justice_league_core": [
        "Clark", "Bruce", "Diana", "Barry", "Arthur", "Victor", "Hal",
    ],
    "x_men_og": [
        "Charles", "Scott", "Jean", "Hank", "Bobby", "Warren",
    ],
    "brady_bunch": [
        "Mike", "Carol", "Greg", "Marcia", "Peter",
        "Jan", "Bobby", "Cindy",
    ],
    "simpsons": ["Homer", "Marge", "Bart", "Lisa", "Maggie"],
    "parks_rec": ["Leslie", "Ron", "Tom", "April", "Andy", "Ben", "Ann"],
    "office_core": ["Michael", "Jim", "Pam", "Dwight", "Angela", "Kevin", "Oscar"],
    "stranger_things_kids": ["Mike", "Eleven", "Dustin", "Lucas", "Will", "Max"],
    "goonies": ["Mikey", "Mouth", "Chunk", "Data", "Brand", "Andy", "Stef"],
    "lost_boys": ["Michael", "Star", "Sam", "Edgar", "Alan", "Laddie"],
    "sandlot": ["Scotty", "Benny", "Ham", "Squints", "Yeah-Yeah", "Kenny", "Bertram", "Timmy", "Tommy"],
    "mighty_ducks": ["Charlie", "Adam", "Fulton", "Goldberg", "Jesse", "Guy", "Connie", "Averman"],
}

# Combined lookup for all sizes
SETS_BY_SIZE: dict[int, dict[str, list[str]]] = {
    1: SOLOS,
    2: DUOS,
    3: TRIOS,
    4: QUARTETS,
    5: QUINTETS,
}

# Legacy combined dict for backward compatibility
NAME_SETS: dict[str, list[str]] = {}
for size_dict in [SOLOS, DUOS, TRIOS, QUARTETS, QUINTETS, LARGER]:
    NAME_SETS.update(size_dict)


def get_name_set(name: str) -> list[str]:
    """Get names from a specific set.

    Args:
        name: The name of the set (e.g., "beatles", "tmnt")

    Returns:
        List of names in the set

    Raises:
        KeyError: If the set name doesn't exist
    """
    return NAME_SETS[name]


def pick_names_for_count(count: int) -> tuple[str, list[str]]:
    """Pick a name set that matches the requested count.

    For counts 1-5, picks a random set of exactly that size.
    For counts > 5, combines sets to reach the target count.

    Args:
        count: Number of names needed

    Returns:
        Tuple of (set_description, list of names)
    """
    if count <= 0:
        return ("empty", [])

    if count <= 5:
        # Pick a random set of exactly this size
        size_sets = SETS_BY_SIZE[count]
        set_name = random.choice(list(size_sets.keys()))
        return (set_name, list(size_sets[set_name]))

    # For count > 5, combine sets
    names: list[str] = []
    set_names: list[str] = []
    remaining = count

    while remaining > 0:
        if remaining >= 5:
            # Add a quintet
            set_name = random.choice(list(QUINTETS.keys()))
            names.extend(QUINTETS[set_name])
            set_names.append(set_name)
            remaining -= 5
        elif remaining in SETS_BY_SIZE:
            # Add a set of exact size
            size_sets = SETS_BY_SIZE[remaining]
            set_name = random.choice(list(size_sets.keys()))
            names.extend(size_sets[set_name])
            set_names.append(set_name)
            remaining = 0
        else:
            # Should not happen for counts 1-5, but just in case
            # Use a larger set and take what we need
            if remaining > 5:
                larger_name = random.choice(list(LARGER.keys()))
                larger_set = LARGER[larger_name]
                take = min(remaining, len(larger_set))
                names.extend(larger_set[:take])
                set_names.append(larger_name)
                remaining -= take
            else:
                break

    combined_name = " + ".join(set_names)
    return (combined_name, names)


def pick_names(count: int, name_set: str | None = None) -> list[str]:
    """Pick N names from a set, using size-matched selection when no set specified.

    Args:
        count: Number of names to pick
        name_set: Optional set name. If None, picks a size-matched set.

    Returns:
        List of names (may combine sets if count > set size)

    Raises:
        KeyError: If the specified name_set doesn't exist
    """
    if name_set is None:
        # Use size-matched selection
        _, names = pick_names_for_count(count)
        return names

    # Use specified set
    names = get_name_set(name_set)

    result = []
    for i in range(count):
        result.append(names[i % len(names)])
    return result


def list_sets_by_size() -> dict[int, list[str]]:
    """List available name sets grouped by size.

    Returns:
        Dict mapping size to list of set names
    """
    result: dict[int, list[str]] = {}
    for size, sets in SETS_BY_SIZE.items():
        result[size] = list(sets.keys())
    result[6] = [k for k, v in LARGER.items() if len(v) == 6]
    result[7] = [k for k, v in LARGER.items() if len(v) == 7]
    result[8] = [k for k, v in LARGER.items() if len(v) >= 8]
    return result
