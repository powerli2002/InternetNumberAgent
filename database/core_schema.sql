CREATE TABLE IF NOT EXISTS as_entity (
  asn integer PRIMARY KEY,
  source text,
  opq_id text,
  date text,
  status text,
  descr text,
  descr_cn text,
  aut_name text,
  website text,
  registration_date text,
  last_change_date text,
  org_handle text,
  org_id text,
  org_rank integer,
  org_country text,
  org_country_cn text,
  uuid text,
  org_name text,
  org_name_cn text,
  sibling_as text[],
  administrative text,
  technical text,
  abuse text,
  admin_info json,
  tech_info json,
  abuse_info json,
  as_rank integer,
  type text,
  type_cn text,
  is_ddos_provider boolean,
  is_route boolean,
  as_longitude numeric(32,8),
  as_latitude numeric(32,8),
  geo_country_list text[],
  geo_city_list text[],
  geo_latitude_longitude text[],
  geo_country_list_num integer,
  geo_city_list_num integer,
  geo_latitude_longitude_num integer,
  as_country text,
  as_country_cn text,
  import text[],
  export text[],
  import_as text[],
  export_as text[],
  v4upstream text[],
  v4peer text[],
  v4downstream text[],
  v4propagation text[],
  v4prefixes text[],
  v6upstream text[],
  v6peer text[],
  v6downstream text[],
  v6propagation text[],
  v6prefixes text[]
);

CREATE TABLE IF NOT EXISTS asn_entity (
  asn integer PRIMARY KEY,
  source text,
  country text,
  opq_id text,
  date text,
  status text,
  org_name text,
  uuid text
);

CREATE TABLE IF NOT EXISTS country_entity (
  country_en text,
  country text PRIMARY KEY,
  country_cn text,
  region text,
  population integer,
  internet_users integer,
  internet_users_percentage numeric(32,8),
  gdp_per_capita_cny integer,
  asns text[],
  asns_number integer,
  route_asns text[],
  route_asns_number integer,
  v4prefixes text[],
  v4prefixes_number integer,
  v6prefixes text[],
  v6prefixes_number integer,
  orgs text[],
  orgs_number integer
);

CREATE TABLE IF NOT EXISTS industry_entity (
  url text PRIMARY KEY,
  parent text,
  title text,
  industry text,
  description text,
  key text,
  ip text[],
  ip_prefix text[],
  ip_asn bigint[],
  ip_org text[],
  auth_ip text[],
  auth_ip_prefix text[],
  auth_ip_asn bigint[],
  auth_ip_org text[]
);

CREATE TABLE IF NOT EXISTS ip_bgp_entity (
  prefix cidr NOT NULL,
  prefix_len integer,
  route bigint[],
  bgp bigint NOT NULL,
  name text,
  descr text,
  admin_prefix text,
  admin_route json,
  admin_bgp text,
  org_handle_prefix text,
  org_name_prefix text,
  org_name_cn_prefix text,
  org_uuid_prefix text,
  org_handle_bgp text,
  org_name_bgp text,
  org_name_cn_bgp text,
  org_uuid_bgp text,
  country text,
  source text,
  date text,
  inetnum text,
  rdap text,
  rpki text,
  domain text[],
  domain_num integer,
  domain_auth text[],
  domain_auth_num integer,
  PRIMARY KEY (prefix, bgp)
);

CREATE TABLE IF NOT EXISTS ip_inetnum_entity (
  cidr cidr PRIMARY KEY,
  netname text,
  descr text,
  country text,
  source text,
  admin_c text,
  tech_c text,
  abuse_c text,
  org text,
  org_name text,
  org_name_cn text,
  org_uuid text
);

CREATE TABLE IF NOT EXISTS ip_rdap_entity (
  cidr cidr PRIMARY KEY,
  netname text,
  descr text,
  country text,
  source text,
  admin_c text,
  tech_c text,
  abuse_c text,
  org text,
  org_name text,
  org_name_cn text,
  org_uuid text
);

CREATE TABLE IF NOT EXISTS ip_route_entity (
  cidr cidr PRIMARY KEY,
  descr text,
  origin text,
  mnt_by text,
  last_modified text,
  source text
);

CREATE TABLE IF NOT EXISTS ipv4_entity (
  prefix inet PRIMARY KEY,
  prefix_len integer,
  source text,
  country text,
  org_id text,
  date text,
  status text,
  org_name text,
  sibling_as bigint[],
  uuid text
);

CREATE TABLE IF NOT EXISTS ipv6_bgp_entity (
  prefix cidr NOT NULL,
  prefix_len integer,
  name text,
  descr text,
  route bigint[],
  bgp bigint NOT NULL,
  admin_prefix text,
  admin_route json,
  admin_bgp text,
  org_handle_prefix text,
  org_name_prefix text,
  org_name_cn_prefix text,
  org_uuid_prefix text,
  org_handle_bgp text,
  org_name_bgp text,
  org_name_cn_bgp text,
  org_uuid_bgp text,
  country text,
  source text,
  date text,
  inetnum text,
  rdap text,
  rpki text,
  PRIMARY KEY (prefix, bgp)
);

CREATE TABLE IF NOT EXISTS ipv6_entity (
  prefix inet PRIMARY KEY,
  prefix_len integer,
  source text,
  country text,
  org_id text,
  date text,
  status text,
  org_name text,
  sibling_as bigint[],
  uuid text
);

CREATE TABLE IF NOT EXISTS ipv6_inetnum_entity (
  cidr cidr PRIMARY KEY,
  netname text,
  descr text,
  country text,
  source text,
  admin_c text,
  tech_c text,
  abuse_c text,
  org text,
  org_name text,
  org_name_cn text,
  org_uuid text
);

CREATE TABLE IF NOT EXISTS ipv6_rdap_entity (
  cidr cidr PRIMARY KEY,
  netname text,
  descr text,
  country text,
  source text,
  admin_c text,
  tech_c text,
  abuse_c text,
  org text,
  org_name text,
  org_name_cn text,
  org_uuid text
);

CREATE TABLE IF NOT EXISTS ipv6_route_entity (
  cidr cidr PRIMARY KEY,
  descr text,
  origin text,
  mnt_by text,
  last_modified text,
  source text
);

CREATE TABLE IF NOT EXISTS org_entity (
  uuid text PRIMARY KEY,
  org_country text,
  org_country_cn text,
  org_name text,
  org_name_cn text,
  sibling_as text[],
  v4prefixes text[],
  v6prefixes text[],
  sibling_as_num integer,
  v4prefixes_num integer,
  v6prefixes_num integer
);

CREATE TABLE IF NOT EXISTS website_entity (
  url text PRIMARY KEY,
  title text,
  key text,
  description text,
  industry text,
  ip text[],
  ip_prefix text[],
  auth_ip text[],
  auth_ip_prefix text[]
);

CREATE INDEX IF NOT EXISTS ip_bgp_entity_prefix_idx ON ip_bgp_entity (prefix);
CREATE INDEX IF NOT EXISTS ipv6_bgp_entity_prefix_idx ON ipv6_bgp_entity (prefix);
CREATE INDEX IF NOT EXISTS ipv4_entity_prefix_idx ON ipv4_entity (prefix);
CREATE INDEX IF NOT EXISTS ipv6_entity_prefix_idx ON ipv6_entity (prefix);
